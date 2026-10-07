import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../models/auth_session.dart';

/// Persists the session token in Keystore-backed secure storage (FR-21,
/// PIYA-202 AC3) — never shared_preferences, which is plaintext on disk.
class SessionStorage {
  SessionStorage([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  static const String _tokenKey = 'session_token';
  static const String _expiresAtKey = 'session_expires_at';

  final FlutterSecureStorage _storage;

  /// Writes expiry before token, and rolls back on failure, so a partial
  /// write never leaves a token without an expiry — PIYA-214's auto-login
  /// would otherwise treat that orphan as a live session.
  Future<void> save(AuthSession session) async {
    try {
      await _storage.write(
        key: _expiresAtKey,
        value: session.expiresAt.toUtc().toIso8601String(),
      );
      await _storage.write(key: _tokenKey, value: session.sessionToken);
    } catch (_) {
      await clear();
      rethrow;
    }
  }

  Future<String?> readToken() => _storage.read(key: _tokenKey);

  Future<void> clear() async {
    await _storage.delete(key: _tokenKey);
    await _storage.delete(key: _expiresAtKey);
  }
}
