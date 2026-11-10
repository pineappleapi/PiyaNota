import 'dart:async';
import 'dart:typed_data';

import 'package:dio/dio.dart' show CancelToken, ProgressCallback;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/models/page_edit.dart';
import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/capture/capture_screen.dart';
import 'package:piyanota_application/screens/capture/score_details_screen.dart';
import 'package:piyanota_application/screens/processing/processing_messages.dart';
import 'package:piyanota_application/screens/processing/processing_screen.dart';
import 'package:piyanota_application/services/capture/capture_camera.dart';
import 'package:piyanota_application/services/capture/capture_files.dart';
import 'package:piyanota_application/services/capture/capture_permissions.dart';
import 'package:piyanota_application/services/capture/device_channel.dart';
import 'package:piyanota_application/services/capture/page_image_processor.dart';
import 'package:piyanota_application/services/capture/page_image_source.dart';
import 'package:piyanota_application/services/capture/page_picker.dart';
import 'package:piyanota_application/services/capture/pdf_page_renderer.dart';
import 'package:piyanota_application/services/score_upload_api.dart';
import 'package:piyanota_application/services/session_storage.dart';
import 'package:piyanota_application/services/settings_prefs_service.dart';
import 'package:piyanota_application/state/auth_providers.dart';
import 'package:piyanota_application/state/capture_providers.dart';
import 'package:piyanota_application/state/processing_providers.dart';
import 'package:piyanota_application/state/score_upload_providers.dart';
import 'package:piyanota_application/state/submission_reconcile_providers.dart';

import '../auth/auth_test_harness.dart';
import '../processing/processing_fakes.dart'
    show ScriptedProcessingApi, ScriptedSubmissionCancelApi, running;

/// A real 1x1 PNG, so thumbnails decode without touching disk.
final Uint8List kTinyPng = img.encodePng(img.Image(width: 1, height: 1));

class FakeCaptureCamera implements CaptureCamera {
  FakeCaptureCamera({this.failInit = false, this.failCapture = false});

  bool failInit;
  bool failCapture;
  bool initialized = false;
  bool disposed = false;
  bool? torch;
  Offset? focusedAt;
  int shots = 0;

  @override
  Future<void> initialize() async {
    if (failInit) throw const CameraUnavailableException();
    initialized = true;
  }

  @override
  double get previewAspectRatio => 3 / 4;

  @override
  Widget buildPreview() =>
      const ColoredBox(color: Colors.grey, child: SizedBox.expand());

  @override
  Future<void> setTorch({required bool on}) async => torch = on;

  @override
  Future<void> focusAt(Offset point) async => focusedAt = point;

  @override
  Future<String> takePicture() async {
    if (failCapture) throw const CameraUnavailableException();
    return 'raw-${shots++}.jpg';
  }

  @override
  Future<void> dispose() async => disposed = true;
}

class FakeCapturePermissions implements CapturePermissions {
  FakeCapturePermissions({
    this.camera = PermissionOutcome.granted,
    this.gallery = PermissionOutcome.granted,
  });

  PermissionOutcome camera;
  PermissionOutcome gallery;

  /// What [cameraGranted] reports on resume (e.g. after Settings).
  bool? grantedOnResume;
  int cameraRequests = 0;
  int galleryRequests = 0;
  int settingsOpened = 0;

  @override
  Future<PermissionOutcome> requestCamera() async {
    cameraRequests++;
    return camera;
  }

  @override
  Future<bool> cameraGranted() async =>
      grantedOnResume ?? camera == PermissionOutcome.granted;

  @override
  Future<PermissionOutcome> requestGallery() async {
    galleryRequests++;
    return gallery;
  }

  @override
  Future<bool> openSettings() async {
    settingsOpened++;
    return true;
  }
}

class FakePagePicker implements PagePicker {
  List<String> gallery = const [];
  PickedPdf? pdf;
  bool notAPdf = false;

  @override
  Future<List<String>> pickGalleryImages() async => gallery;

  /// How many times the PDF picker was opened.
  int pdfPicks = 0;

  @override
  Future<PickedPdf?> pickPdf() async {
    pdfPicks++;
    if (notAPdf) throw const NotAPdfException();
    return pdf;
  }
}

/// Prepares by renaming; paths containing "bad" are unreadable images.
class FakePageImageProcessor implements PageImageProcessor {
  final List<String> prepared = [];
  final List<(String, PageEdit)> edits = [];
  Completer<void>? gate;

  @override
  Future<String> prepare(String sourcePath) async {
    await gate?.future;
    if (sourcePath.contains('bad')) throw const UnreadableImageException();
    prepared.add(sourcePath);
    return 'prepared/$sourcePath';
  }

  @override
  Future<String> applyEdit(String path, PageEdit edit) async {
    edits.add((path, edit));
    return '$path+edit${edits.length}';
  }
}

/// Records deletions instead of touching disk.
class FakeCaptureFileStore implements CaptureFileStore {
  final List<String> deleted = [];
  final List<DateTime> staleCleared = [];
  final List<Set<String>> staleKept = [];

  @override
  Future<void> delete(String path) async => deleted.add(path);

  @override
  Future<void> clearStale(
    DateTime before, {
    Set<String> keep = const {},
  }) async {
    staleCleared.add(before);
    staleKept.add(keep);
  }
}

class FakePageImageSource implements PageImageSource {
  const FakePageImageSource([this.size = const Size(300, 400)]);

  final Size size;

  @override
  ImageProvider imageFor(String path) => MemoryImage(kTinyPng);

  @override
  Future<Size> sizeOf(String path) async => size;
}

class FakeDeviceChannel implements DeviceChannel {
  FakeDeviceChannel({this.pages = 3, this.problem});

  int pages;
  PdfProblem? problem;

  @override
  Future<int> sdkInt() async => 34;

  @override
  Future<int> pdfPageCount(String path) async {
    if (problem case final p?) throw PdfUnreadableException(p);
    return pages;
  }
}

class FakePdfDocument implements PdfPreviewDocument {
  FakePdfDocument(this.pageCount);

  @override
  final int pageCount;
  final List<int> rendered = [];
  bool closed = false;

  @override
  Future<Uint8List> renderPage(int index, {required double width}) async {
    rendered.add(index);
    return kTinyPng;
  }

  @override
  Future<void> close() async => closed = true;
}

class FakePdfPageRenderer implements PdfPageRenderer {
  FakePdfPageRenderer({int pages = 30}) : document = FakePdfDocument(pages);

  final FakePdfDocument document;
  PdfProblem? problem;

  @override
  Future<PdfPreviewDocument> open(String path) async {
    if (problem case final p?) throw PdfUnreadableException(p);
    return document;
  }
}

class ScriptedScoreUploadApi implements ScoreUploadApi {
  Future<SubmittedJob> Function()? onSubmit;
  final List<List<String>> imageCalls = [];
  final List<String> pdfCalls = [];
  final List<ScoreDetails> detailsSent = [];
  final List<int?> fallbackTemposSent = [];

  static const job = SubmittedJob(
    jobId: 'job-42',
    pageCount: 2,
    status: 'queued',
  );

  /// `replacesJobId` per submit, in call order (PIYA-207 AC12).
  final List<String?> replacesSent = [];

  /// `clientSubmissionId` per submit, in call order (Task 3).
  final List<String?> clientIdsSent = [];

  /// The token passed with the latest submit.
  CancelToken? lastCancelToken;

  /// The progress callback passed with the latest submit.
  ProgressCallback? lastProgress;

  /// The answer arrives as if the abort came too late (a failure that wins
  /// the race against Cancel sending).
  bool ignoreCancel = false;

  /// Like the real API, a cancel wins over a still-pending answer.
  Future<SubmittedJob> _answer(
    CancelToken? cancelToken,
    ProgressCallback? onSendProgress,
  ) {
    lastCancelToken = cancelToken;
    lastProgress = onSendProgress;
    final answer = onSubmit?.call() ?? Future.value(job);
    if (cancelToken == null || ignoreCancel) return answer;
    return Future.any([
      answer,
      cancelToken.whenCancel.then<SubmittedJob>(
        (_) => throw const UploadCancelledException(),
      ),
    ]);
  }

  @override
  Future<SubmittedJob> submitImages({
    required ScoreDetails details,
    required List<String> imagePaths,
    CancelToken? cancelToken,
    String? replacesJobId,
    int? fallbackTempoBpm,
    String? clientSubmissionId,
    ProgressCallback? onSendProgress,
  }) {
    detailsSent.add(details);
    fallbackTemposSent.add(fallbackTempoBpm);
    replacesSent.add(replacesJobId);
    clientIdsSent.add(clientSubmissionId);
    imageCalls.add(imagePaths);
    return _answer(cancelToken, onSendProgress);
  }

  @override
  Future<SubmittedJob> submitPdf({
    required ScoreDetails details,
    required String pdfPath,
    CancelToken? cancelToken,
    String? replacesJobId,
    int? fallbackTempoBpm,
    String? clientSubmissionId,
    ProgressCallback? onSendProgress,
  }) {
    detailsSent.add(details);
    fallbackTemposSent.add(fallbackTempoBpm);
    replacesSent.add(replacesJobId);
    clientIdsSent.add(clientSubmissionId);
    pdfCalls.add(pdfPath);
    return _answer(cancelToken, onSendProgress);
  }
}

/// Everything Capture talks to, faked, plus the overrides that install it.
class CaptureHarness {
  CaptureHarness({
    FakeCapturePermissions? permissions,
    FakeDeviceChannel? device,
    int? settingsDefaultTempo,
  }) : permissions = permissions ?? FakeCapturePermissions(),
       device = device ?? FakeDeviceChannel() {
    // Submit reads the Settings default tempo whenever Speed is "Not sure"
    // (PIYA-212 AC8), so every harness gets a preferences store.
    SharedPreferences.setMockInitialValues({
      SettingsPrefsService.defaultTempoKey: ?settingsDefaultTempo,
    });
  }

  final FakeCapturePermissions permissions;
  final FakeDeviceChannel device;
  final picker = FakePagePicker();
  final pdfRenderer = FakePdfPageRenderer();
  final processor = FakePageImageProcessor();
  final upload = ScriptedScoreUploadApi();
  final cancelApi = ScriptedSubmissionCancelApi();

  /// Answers polls for jobs a test seeds into the tracker.
  final processing = ScriptedProcessingApi([running(10)]);
  final files = FakeCaptureFileStore();
  final secureStorage = FaultySecureStorage({'session_token': 'sess_t'});
  final List<FakeCaptureCamera> cameras = [];
  bool cameraFailsInit = false;

  FakeCaptureCamera? get camera => cameras.isEmpty ? null : cameras.last;

  /// Overrides for providers the harness leaves real.
  final List<Override> extraOverrides = [];

  List<Override> get overrides => [
    ...extraOverrides,
    capturePermissionsProvider.overrideWithValue(permissions),
    deviceChannelProvider.overrideWithValue(device),
    pagePickerProvider.overrideWithValue(picker),
    pdfPageRendererProvider.overrideWithValue(pdfRenderer),
    pageImageProcessorProvider.overrideWithValue(processor),
    pageImageSourceProvider.overrideWithValue(const FakePageImageSource()),
    captureCameraFactoryProvider.overrideWithValue(() {
      final camera = FakeCaptureCamera(failInit: cameraFailsInit);
      cameras.add(camera);
      return camera;
    }),
    scoreUploadApiProvider.overrideWithValue(upload),
    processingApiProvider.overrideWithValue(processing),
    submissionCancelApiProvider.overrideWithValue(cancelApi),
    captureFileStoreProvider.overrideWithValue(files),
    sessionStorageProvider.overrideWithValue(SessionStorage(secureStorage)),
  ];
}

const kDetails = ScoreDetails(title: 'Ave Maria');
const kLibraryMarker = 'ROUTE:library';
const kLoginMarker = 'ROUTE:login';

/// Pumps a library stand-in with Capture pushed on top, so Close, submit
/// and Back can be checked against a real stack.
Future<void> pumpCapture(
  WidgetTester tester,
  CaptureHarness harness, {
  ScoreDetails details = kDetails,
  Size size = const Size(400, 800),
  double textScale = 1,
  bool startOnDetails = false,
  WholeRetakeArguments? wholeRetake,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: harness.overrides,
      child: MaterialApp(
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context)
              .copyWith(textScaler: TextScaler.linear(textScale)),
          child: child!,
        ),
        initialRoute: AppRoutes.scoreLibrary,
        routes: {
          AppRoutes.scoreLibrary: (_) =>
              const Scaffold(body: Text(kLibraryMarker)),
          AppRoutes.login: (_) => const Scaffold(body: Text(kLoginMarker)),
          AppRoutes.capture: (context) {
            final args = ModalRoute.of(context)!.settings.arguments;
            return ScoreDetailsScreen(
              wholeRetake: args is WholeRetakeArguments ? args : null,
            );
          },
          AppRoutes.capturePages: (context) {
            final args =
                ModalRoute.of(context)!.settings.arguments!
                    as CapturePagesArguments;
            return CaptureScreen(
              details: args.details,
              wholeRetake: args.wholeRetake,
              resume: args.resume,
            );
          },
          AppRoutes.processing: (context) => ProcessingStandIn(
            ModalRoute.of(context)!.settings.arguments! as ProcessingArguments,
          ),
        },
      ),
    ),
  );
  final navigator = tester.state<NavigatorState>(find.byType(Navigator));
  if (wholeRetake != null) {
    navigator.pushNamed(AppRoutes.capture, arguments: wholeRetake);
  } else if (startOnDetails) {
    navigator.pushNamed(AppRoutes.capture);
  } else {
    navigator.pushNamed(
      AppRoutes.capturePages,
      arguments: CapturePagesArguments(details: details),
    );
  }
  await tester.pumpAndSettle();
}

/// From a failed upload on Processing back to Capture with its pages.
Future<void> backToEditPages(WidgetTester tester) async {
  await tester.tap(find.text(ProcessingMessages.backToEditPages));
  await tester.pumpAndSettle();
}

/// Processing as Capture tests see it: the real upload step (progress,
/// failure, cancel), then a marker naming the job once the 202 lands.
class ProcessingStandIn extends ConsumerStatefulWidget {
  const ProcessingStandIn(this.args, {super.key});

  final ProcessingArguments args;

  @override
  ConsumerState<ProcessingStandIn> createState() => _ProcessingStandInState();
}

class _ProcessingStandInState extends ConsumerState<ProcessingStandIn> {
  late String? _jobId = widget.args.jobId;

  @override
  Widget build(BuildContext context) {
    final key = widget.args.clientSubmissionId;
    if (_jobId == null && key != null) {
      _jobId = ref.watch(
        scoreUploadsProvider.select((uploads) => uploads[key]?.jobId),
      );
    }
    if (_jobId case final jobId?) {
      return Scaffold(
        body: Text('ROUTE:processing $jobId ${widget.args.title}'),
      );
    }
    return ProcessingScreen(
      jobId: null,
      title: widget.args.title,
      clientSubmissionId: key,
    );
  }
}
