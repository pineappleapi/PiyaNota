import 'package:flutter/foundation.dart';

/// Backend connection settings, injected at build time via `--dart-define`
/// so no environment-specific URL is baked into source.
///
/// The Module 3 auth endpoints (PIYA-301/302) define response schemas but
/// not URL paths — [loginPath]/[signUpPath] are assumed and must be
/// reconciled with the Flask API once it lands (PIYA-214).
class ApiConfig {
  ApiConfig._();

  /// e.g. `--dart-define=API_BASE_URL=https://api.example.com`. Empty means
  /// "no real backend configured"; only valid while [useFakeAuth] is true.
  static const String baseUrl = String.fromEnvironment('API_BASE_URL');

  /// Defaults to true only in debug, because the Module 3 API isn't deployed
  /// yet. Despite the name it gates every fake (auth and Score Library),
  /// since the fake library can only resolve tokens the fake auth issued;
  /// pass `--dart-define=USE_FAKE_AUTH=false` to hit [baseUrl] instead.
  /// Profile and release builds — the ones handed to choir testers — default
  /// to false so they can't silently accept the fake demo credentials.
  static const bool useFakeAuth = bool.fromEnvironment(
    'USE_FAKE_AUTH',
    defaultValue: kDebugMode,
  );

  static const String loginPath = '/api/auth/login';
  static const String signUpPath = '/api/auth/signup';
  // PIYA-303/304 — same caveat: assumed paths, reconcile in PIYA-214.
  static const String passwordResetRequestPath =
      '/api/auth/password-reset/request';
  static const String passwordResetConfirmPath =
      '/api/auth/password-reset/confirm';
  // PIYA-322 pins this path (all Module 3 routes sit under `/api`), so
  // unlike the paths above it is not an assumption.
  static const String changePasswordPath = '/api/auth/change-password';

  // PIYA-308/309 define methods and schemas but not paths or the search
  // parameter name — all three are assumed; reconcile in PIYA-215.
  static const String scoreLibraryPath = '/api/scores';
  static const String scoreLibrarySearchParam = 'search';
  static String scorePath(int scoreId) => '$scoreLibraryPath/$scoreId';

  // PIYA-101/310 define multipart parts, fields and error codes but not
  // paths — both are assumed; reconcile in PIYA-215.
  static const String submitImagesPath = '/api/jobs';
  static const String submitPdfPath = '/api/jobs/pdf';

  // PIYA-102/114/116 give methods and schemas but no paths; all three are
  // assumed under the PIYA-101 jobs path. Reconcile in PIYA-216. PIYA-102's
  // `complete` response must also carry `scoreId` for Processing to open
  // Playback (see ProcessingStatus.scoreId).
  static String jobStatusPath(String jobId) =>
      '$submitImagesPath/${Uri.encodeComponent(jobId)}';
  static String cancelJobPath(String jobId) => '${jobStatusPath(jobId)}/cancel';

  /// PIYA-116: multipart with a `pageIndex` field (0-based, as PIYA-101)
  /// and one `page` JPEG part — part names assumed too.
  static String resubmitPagePath(String jobId) =>
      '${jobStatusPath(jobId)}/resubmit';

  /// PIYA-103 (Playback's result: audio, page images, timing, review).
  /// Assumed path, reconcile in PIYA-216. PIYA-103 is written per job, but
  /// the library (PIYA-308) only gives Playback a `scoreId`, so this
  /// assumes a by-score route exists.
  static String scoreResultPath(int scoreId) => '${scorePath(scoreId)}/result';

  /// PIYA-310 rasterises the whole PDF (up to 15 s for 20 pages, AC6)
  /// before it replies, on top of the upload itself.
  static const Duration pdfReceiveTimeout = Duration(seconds: 90);

  /// Upload body time limit. Up to 20 pages at ~1-3 MB each (PIYA-101
  /// AC10) is tens of MB; 120 s still allows a slow (~2-3 Mbit/s) mobile
  /// link, while a stalled upload no longer hangs forever.
  static const Duration uploadSendTimeout = Duration(seconds: 120);

  // PIYA-301/302 AC: endpoint responds within 2s under normal load. The
  // client allows headroom for slow mobile networks before declaring the
  // request a connectivity failure.
  static const Duration connectTimeout = Duration(seconds: 10);
  static const Duration receiveTimeout = Duration(seconds: 15);

  static const String _requiredScheme = 'https';

  /// Why this build's backend settings are unusable, or null if they're fine.
  ///
  /// Checked at startup so a misconfigured APK fails on launch, not on the
  /// first Log In tap with a misleading "something went wrong" (dio uses
  /// dart:io, so Android's cleartext policy would not block http either).
  static String? configurationError() => configurationErrorFor(
    useFakeAuth: useFakeAuth,
    baseUrl: baseUrl,
    allowCleartext: kDebugMode,
  );

  /// [configurationError] with its inputs exposed, since the real ones are
  /// compile-time constants tests can't vary.
  ///
  /// [allowCleartext] keeps plain http usable for a local Flask server
  /// (e.g. `http://10.0.2.2:5000` from the emulator) in debug only; any
  /// build a tester receives must use TLS (FR-17 / NFR-7).
  @visibleForTesting
  static String? configurationErrorFor({
    required bool useFakeAuth,
    required String baseUrl,
    required bool allowCleartext,
  }) {
    if (useFakeAuth) return null;
    if (baseUrl.isEmpty) {
      return 'USE_FAKE_AUTH=false requires --dart-define=API_BASE_URL=<url>';
    }
    final uri = Uri.tryParse(baseUrl);
    if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
      return 'API_BASE_URL is not an absolute URL: "$baseUrl"';
    }
    if (!allowCleartext && uri.scheme != _requiredScheme) {
      return 'API_BASE_URL must use https outside debug builds: "$baseUrl"';
    }
    return null;
  }
}
