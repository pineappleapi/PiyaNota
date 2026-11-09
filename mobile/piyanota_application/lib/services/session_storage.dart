import 'package:clock/clock.dart';
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

  /// Kept beside the token so Settings can show the signed-in address
  /// (PIYA-212 AC1) offline, without a PIYA-306 round trip. Not a secret,
  /// but it is account data and belongs with the session it describes.
  static const String _emailKey = 'session_email';

  final FlutterSecureStorage _storage;

  /// Writes expiry and email before token, and rolls back on failure, so a
  /// partial write never leaves a token without an expiry — PIYA-214's
  /// auto-login would otherwise treat that orphan as a live session.
  Future<void> save(AuthSession session) async {
    try {
      await _storage.write(key: _emailKey, value: session.email);
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

  /// The address the current session was issued to, or null when none is
  /// stored (e.g. a session saved by a build before PIYA-212) or it can't
  /// be decrypted. Display only — never used to authorise anything.
  Future<String?> readEmail() async {
    try {
      return await _storage.read(key: _emailKey);
    } on PlatformException catch (e) {
      debugPrint('Unreadable session email: ${e.code}');
      return null;
    }
  }

  /// PIYA-212 AC5: true only for a non-empty token whose stored expiry
  /// parses and is still ahead of [now]. A token with no readable expiry is
  /// the orphan [save] guards against, so it counts as logged out.
  Future<bool> hasValidSession({DateTime? now}) async {
    final token = await readToken();
    if (token == null || token.isEmpty) return false;
    final String? rawExpiry;
    try {
      rawExpiry = await _storage.read(key: _expiresAtKey);
    } on PlatformException catch (e) {
      debugPrint('Unreadable session expiry: ${e.code}');
      return false;
    }
    final expiresAt = rawExpiry == null ? null : DateTime.tryParse(rawExpiry);
    if (expiresAt == null) return false;
    return expiresAt.isAfter(now ?? clock.now());
  }

  /// Deletes every key even if one delete fails, so a logout never strands
  /// a token behind a failed expiry delete.
  Future<void> clear() async {
    Object? firstError;
    StackTrace? firstStack;
    for (final key in const [_tokenKey, _expiresAtKey, _emailKey]) {
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
