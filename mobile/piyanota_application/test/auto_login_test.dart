import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/app.dart';
import 'package:piyanota_application/models/score_summary.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/auth/login_screen.dart';
import 'package:piyanota_application/screens/library/library_messages.dart';
import 'package:piyanota_application/screens/library/score_library_screen.dart';
import 'package:piyanota_application/screens/onboarding/widgets/splash_overlay.dart';
import 'package:piyanota_application/screens/playback/playback_screen.dart';
import 'package:piyanota_application/screens/processing/processing_screen.dart';
import 'package:piyanota_application/screens/settings/settings_messages.dart';
import 'package:piyanota_application/screens/settings/settings_screen.dart';
import 'package:piyanota_application/services/demo/playback_demo.dart';
import 'package:piyanota_application/services/fake_auth_api.dart';
import 'package:piyanota_application/services/fake_score_library_api.dart';
import 'package:piyanota_application/services/fake_score_result_api.dart';
import 'package:piyanota_application/services/score_library_api.dart';
import 'package:piyanota_application/services/session_storage.dart';
import 'package:piyanota_application/state/auth_providers.dart';
import 'package:piyanota_application/state/playback_providers.dart';
import 'package:piyanota_application/state/processing_providers.dart';
import 'package:piyanota_application/state/scan_job_store.dart';
import 'package:piyanota_application/state/score_library_providers.dart';
import 'package:piyanota_application/state/work_owner.dart';

import 'playback/playback_fakes.dart';
import 'processing/processing_fakes.dart' hide appContainer;

/// Not a file, so the fake result fails at once instead of waiting on
/// real file IO the test clock never runs (as in library_flow_test).
final _unwrittenDemo = PlaybackDemoFiles(
  tracks: {
    for (final voice in VoicePart.values)
      voice: Uri.file('/unwritten/${voice.name}.wav'),
  },
  page: Uri.file('/unwritten/score_page_1.png'),
  timing: Uri.parse('https://unwritten.test/timing.json'),
  timingWithoutTenor: Uri.parse('https://unwritten.test/timing_t.json'),
);

class _OfflineLibraryApi implements ScoreLibraryApi {
  @override
  Future<List<ScoreSummary>> fetchLibrary({String? query}) async =>
      throw const ScoreLibraryNetworkException();

  @override
  Future<void> deleteScore(int scoreId) async {}

  @override
  Future<ScoreSummary> updateScore(
    int scoreId, {
    required String title,
    String? arranger,
  }) => throw UnimplementedError();

  @override
  Future<void> recordOpened(int scoreId) async {}
}

/// A session check that answers only when the test says so.
class _SlowSessionStorage extends SessionStorage {
  final Completer<bool> answer = Completer();

  @override
  Future<bool> hasValidSession({DateTime? now}) => answer.future;
}

/// Marking the session signed in fails, so the launch check throws.
class _BrokenSignedIn extends SignedIn {
  @override
  void set(bool value) => throw StateError('broken');
}

/// PIYA-202-V2.2: a stored, unexpired session skips Login on launch.
void main() {
  const settle = Duration(seconds: 2);

  /// A demo-account token the fake issued in an earlier run of the app.
  const demoToken = 'fake_sess_1_0_${FakeAuthApi.demoEmail}';

  Map<String, String> storedSession({
    String token = demoToken,
    Duration expiresIn = const Duration(days: 30),
  }) => {
    'session_token': token,
    'session_expires_at': DateTime.now()
        .toUtc()
        .add(expiresIn)
        .toIso8601String(),
    'session_email': FakeAuthApi.demoEmail,
  };

  Future<String?> storedToken() =>
      const FlutterSecureStorage().read(key: 'session_token');

  /// A cold start: a fresh ProviderScope over whatever is stored. Storage
  /// is set up by the caller, so a second call is the next launch.
  Future<void> launch(
    WidgetTester tester, {
    List<Override> overrides = const [],
  }) async {
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(
      ProviderScope(
        key: UniqueKey(),
        overrides: [
          fakeAuthApiProvider.overrideWithValue(
            FakeAuthApi(latency: Duration.zero),
          ),
          playbackEngineFactoryProvider.overrideWithValue(
            FakePlaybackEngine.new,
          ),
          scoreResultApiProvider.overrideWith(
            (ref) => FakeScoreResultApi(
              sessionStorage: ref.watch(sessionStorageProvider),
              accountForToken: ref.watch(fakeAuthApiProvider).accountForToken,
              library:
                  ref.watch(scoreLibraryApiProvider) as FakeScoreLibraryApi,
              processing: ref.watch(fakeProcessingApiProvider),
              demoFiles: () async => _unwrittenDemo,
            ),
          ),
          ...overrides,
        ],
        child: const PiyaNotaApp(),
      ),
    );
    await tester.pump();
    await tester.pump(splashIntroDuration);
    await tester.pump(FakeScoreLibraryApi.defaultLatency + settle);
  }

  setUp(() {
    SharedPreferences.setMockInitialValues({'onboarding_completed': true});
  });

  testWidgets('a valid stored session opens the Library', (tester) async {
    FlutterSecureStorage.setMockInitialValues(storedSession());
    await launch(tester);

    expect(find.byType(LoginScreen), findsNothing);
    expect(find.byType(ScoreLibraryScreen), findsOneWidget);
    expect(find.text('Bahay Kubo'), findsOneWidget);
  });

  testWidgets('an expired session opens Login', (tester) async {
    FlutterSecureStorage.setMockInitialValues(
      storedSession(expiresIn: const Duration(minutes: -1)),
    );
    await launch(tester);

    expect(find.byType(LoginScreen), findsOneWidget);
    expect(find.byType(ScoreLibraryScreen), findsNothing);
  });

  testWidgets('a 401 on the library load clears the session and opens '
      'Login', (tester) async {
    // Unexpired, but the server doesn't know it (revoked, say).
    FlutterSecureStorage.setMockInitialValues(
      storedSession(token: 'fake_sess_9_0_nobody@example.com'),
    );
    await launch(tester);

    expect(find.byType(LoginScreen), findsOneWidget);
    expect(find.byType(ScoreLibraryScreen), findsNothing);
    expect(await storedToken(), isNull);
  });

  testWidgets('offline with a valid token opens the Library in its offline '
      'state', (tester) async {
    FlutterSecureStorage.setMockInitialValues(storedSession());
    await launch(
      tester,
      overrides: [
        scoreLibraryApiProvider.overrideWithValue(_OfflineLibraryApi()),
      ],
    );

    expect(find.byType(LoginScreen), findsNothing);
    expect(find.text(LibraryMessages.loadNetworkError), findsOneWidget);
    expect(find.text(LibraryMessages.retry), findsOneWidget);
    expect(await storedToken(), demoToken);
  });

  testWidgets('logout clears the session, so the next start opens Login', (
    tester,
  ) async {
    FlutterSecureStorage.setMockInitialValues(storedSession());
    await launch(tester);
    expect(find.byType(ScoreLibraryScreen), findsOneWidget);

    tester
        .state<NavigatorState>(find.byType(Navigator))
        .pushNamed(AppRoutes.settings);
    // Settings fills in its saved defaults before the list stops moving.
    await tester.pumpAndSettle();
    // Settings builds its rows lazily: drag until Log out exists.
    final logOutRow = find.text(SettingsMessages.logOut);
    await tester.dragUntilVisible(
      logOutRow,
      find
          .descendant(
            of: find.byType(SettingsScreen),
            matching: find.byType(Scrollable),
          )
          .first,
      const Offset(0, -120),
    );
    // Centred, clear of the bottom bar.
    await Scrollable.ensureVisible(tester.element(logOutRow), alignment: 0.5);
    await tester.pumpAndSettle();
    await tester.tap(logOutRow);
    await tester.pump();
    await tester.pump(settle);
    await tester.tap(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.text(SettingsMessages.logOut),
      ),
    );
    await tester.pump();
    await tester.pump(settle);
    expect(find.byType(LoginScreen), findsOneWidget);
    expect(await storedToken(), isNull);

    await launch(tester);
    expect(find.byType(LoginScreen), findsOneWidget);
    expect(find.byType(ScoreLibraryScreen), findsNothing);
  });

  testWidgets('a cold start from a notification tap opens Playback for that '
      'score', (tester) async {
    FlutterSecureStorage.setMockInitialValues(storedSession());
    final device = FakeScanTrackingService()..launchJob = 'job-a';
    final finished = DateTime.now().toUtc();
    final store = MemoryScanJobStore(
      ScanJobStore.encodeJobs([
        TrackedJob(
          jobId: 'job-a',
          title: 'Paraiso',
          phase: TrackedPhase.complete,
          scoreId: 102,
          createdAt: finished,
          finishedAt: finished,
        ),
      ]),
    );
    await launch(
      tester,
      overrides: [
        scanTrackingServiceProvider.overrideWithValue(device),
        scanJobStoreProvider.overrideWithValue(store),
      ],
    );

    final playback = tester.widget<PlaybackScreen>(find.byType(PlaybackScreen));
    expect(playback.scoreId, 102);
    expect(find.byType(LoginScreen), findsNothing);
    // Back goes to the Library under it.
    final navigator = tester.state<NavigatorState>(find.byType(Navigator));
    expect(navigator.canPop(), isTrue);
    expect(device.launchJob, isNull, reason: 'taken, so it opens once');
  });

  testWidgets('a session check that throws opens Login, not a blank '
      'screen', (tester) async {
    FlutterSecureStorage.setMockInitialValues(storedSession());
    await launch(
      tester,
      overrides: [signedInProvider.overrideWith(_BrokenSignedIn.new)],
    );

    expect(find.byType(LoginScreen), findsOneWidget);
  });

  testWidgets('a launch job missing from the restored scans is dropped, '
      'not opened later', (tester) async {
    FlutterSecureStorage.setMockInitialValues(storedSession());
    final device = FakeScanTrackingService()..launchJob = 'job-x';
    await launch(
      tester,
      overrides: [
        scanTrackingServiceProvider.overrideWithValue(device),
        scanJobStoreProvider.overrideWithValue(MemoryScanJobStore()),
      ],
    );
    expect(find.byType(ScoreLibraryScreen), findsOneWidget);

    // The same job turns up later, e.g. a new scan reusing the id.
    appContainer(tester).read(processingJobsProvider.notifier).track('job-x');
    await tester.pump();
    await tester.pump(settle);

    expect(find.byType(ProcessingScreen), findsNothing);
    expect(find.byType(ScoreLibraryScreen), findsOneWidget);
  });

  testWidgets('a session check slower than the splash shows the blank '
      'placeholder, never Login, then the Library', (tester) async {
    FlutterSecureStorage.setMockInitialValues(storedSession());
    final storage = _SlowSessionStorage();
    await launch(
      tester,
      overrides: [sessionStorageProvider.overrideWithValue(storage)],
    );

    expect(find.byType(SplashOverlay), findsNothing);
    expect(find.byType(LoginScreen), findsNothing);
    expect(find.byType(ScoreLibraryScreen), findsNothing);

    storage.answer.complete(true);
    await tester.pump();
    await tester.pump(FakeScoreLibraryApi.defaultLatency);
    await tester.pump(settle);
    expect(find.byType(LoginScreen), findsNothing);
    expect(find.byType(ScoreLibraryScreen), findsOneWidget);
  });
}
