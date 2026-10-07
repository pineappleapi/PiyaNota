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
  /// yet; pass `--dart-define=USE_FAKE_AUTH=false` to hit [baseUrl] instead.
  /// Profile and release builds — the ones handed to choir testers — default
  /// to false so they can't silently accept the fake demo credentials.
  static const bool useFakeAuth = bool.fromEnvironment(
    'USE_FAKE_AUTH',
    defaultValue: kDebugMode,
  );

  static const String loginPath = '/api/auth/login';
  static const String signUpPath = '/api/auth/signup';

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
