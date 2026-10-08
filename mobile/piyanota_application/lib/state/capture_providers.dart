import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../config/api_config.dart';
import '../services/capture/capture_camera.dart';
import '../services/capture/capture_files.dart';
import '../services/capture/capture_permissions.dart';
import '../services/capture/device_channel.dart';
import '../services/capture/page_image_processor.dart';
import '../services/capture/page_image_source.dart';
import '../services/capture/page_picker.dart';
import '../services/fake_score_library_api.dart';
import '../services/fake_score_upload_api.dart';
import '../services/score_upload_api.dart';
import 'auth_providers.dart';
import 'processing_providers.dart';
import 'score_library_providers.dart';

/// Capture's working files (prepared pages, edits, copied PDFs) live in
/// the app's temp folder, which Android may clear; they are only needed
/// until the upload finishes.
Future<Directory> captureWorkingDirectory() async {
  final temp = await getTemporaryDirectory();
  final dir = Directory('${temp.path}${Platform.pathSeparator}capture');
  return dir.create(recursive: true);
}

final deviceChannelProvider = Provider<DeviceChannel>(
  (ref) => MethodChannelDeviceChannel(),
);

final capturePermissionsProvider = Provider<CapturePermissions>(
  (ref) => PluginCapturePermissions(ref.watch(deviceChannelProvider)),
);

final pagePickerProvider = Provider<PagePicker>(
  (ref) => PluginPagePicker(captureWorkingDirectory),
);

final pageImageProcessorProvider = Provider<PageImageProcessor>(
  (ref) => IsolatePageImageProcessor(captureWorkingDirectory),
);

final captureFileStoreProvider = Provider<CaptureFileStore>(
  (ref) => DiskCaptureFileStore(captureWorkingDirectory),
);

final pageImageSourceProvider = Provider<PageImageSource>(
  (ref) => const FilePageImageSource(),
);

/// A factory, not an instance: the screen needs a fresh camera each time
/// it comes back from the background.
final captureCameraFactoryProvider = Provider<CaptureCameraFactory>(
  (ref) => PluginCaptureCamera.new,
);

/// Fake until Module 3 is deployed, under the same flag as the other fakes.
/// The fake writes into the fake library so a new score appears there.
final scoreUploadApiProvider = Provider<ScoreUploadApi>((ref) {
  final sessionStorage = ref.watch(sessionStorageProvider);
  if (ApiConfig.useFakeAuth) {
    final library = ref.watch(scoreLibraryApiProvider);
    return FakeScoreUploadApi(
      sessionStorage: sessionStorage,
      accountForToken: ref.watch(fakeAuthApiProvider).accountForToken,
      library: library is FakeScoreLibraryApi
          ? library
          : throw StateError('Fake upload needs the fake library'),
      // Registers each job so Processing (PIYA-207) can poll it.
      jobs: ref.watch(fakeProcessingApiProvider),
    );
  }
  final configError = ApiConfig.configurationError();
  if (configError != null) throw StateError(configError);
  return HttpScoreUploadApi(ref.watch(dioProvider), sessionStorage);
});
