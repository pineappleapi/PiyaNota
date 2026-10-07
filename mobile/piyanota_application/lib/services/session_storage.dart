import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
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
      // A rollback failure must not mask the write failure the caller maps
      // to a user-facing message.
      try {
        await clear();
      } catch (clearError) {
        debugPrint('Session rollback failed: $clearError');
      }
      rethrow;
    }
  }

  /// Returns null, and wipes the entry, when the stored ciphertext can't be
  /// decrypted — e.g. data carried to a new phone without its Keystore key.
  /// Treating that as "logged out" beats crashing auto-login (PIYA-214).
  Future<String?> readToken() async {
    try {
      return await _storage.read(key: _tokenKey);
    } on PlatformException catch (e) {
      debugPrint('Unreadable session token, clearing: ${e.code}');
      try {
        await clear();
      } on PlatformException catch (clearError) {
        debugPrint('Session clear failed: ${clearError.code}');
      }
      return null;
    }
  }

  /// Deletes both keys even if the first delete fails, so a logout never
  /// strands a token behind a failed expiry delete.
  Future<void> clear() async {
    Object? firstError;
    StackTrace? firstStack;
    for (final key in const [_tokenKey, _expiresAtKey]) {
      try {
        await _storage.delete(key: key);
      } catch (e, stack) {
        firstError ??= e;
        firstStack ??= stack;
      }
    }
    if (firstError != null) Error.throwWithStackTrace(firstError, firstStack!);
  }
}
