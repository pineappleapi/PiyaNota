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

  /// Defaults to true in debug/profile because the Module 3 API isn't
  /// deployed yet; pass `--dart-define=USE_FAKE_AUTH=false` to hit [baseUrl]
  /// instead. Release builds default to false so a choir-testing APK can't
  /// silently ship accepting the fake demo credentials.
  static const bool useFakeAuth = bool.fromEnvironment(
    'USE_FAKE_AUTH',
    defaultValue: !kReleaseMode,
  );

  static const String loginPath = '/api/auth/login';
  static const String signUpPath = '/api/auth/signup';

  // PIYA-301/302 AC: endpoint responds within 2s under normal load. The
  // client allows headroom for slow mobile networks before declaring the
  // request a connectivity failure.
  static const Duration connectTimeout = Duration(seconds: 10);
  static const Duration receiveTimeout = Duration(seconds: 15);
}
