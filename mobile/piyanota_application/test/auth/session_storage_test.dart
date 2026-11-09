import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/services/session_storage.dart';

import 'auth_test_harness.dart';

const _token = 'session_token';
const _expiry = 'session_expires_at';
const _email = 'session_email';

void main() {
  test('save writes token and expiry', () async {
    final backing = FaultySecureStorage();
    await SessionStorage(backing).save(testSession());

    expect(backing.values[_token], 'sess_a1b2c3d4');
    expect(backing.values[_expiry], '2026-11-06T00:00:00.000Z');
  });

  test('failed token write rolls back the expiry and rethrows', () async {
    final backing = FaultySecureStorage()..failWritesFor.add(_token);

    await expectLater(
      SessionStorage(backing).save(testSession()),
      throwsA(isA<PlatformException>()),
    );
    expect(backing.values, isEmpty);
  });

  test('a failing rollback does not mask the original write error', () async {
    final backing = FaultySecureStorage()
      ..failWritesFor.add(_token)
      ..failDeletesFor.add(_token);

    await expectLater(
      SessionStorage(backing).save(testSession()),
      throwsA(
        isA<PlatformException>().having(
          (e) => e.code,
          'code',
          'test-write-failed',
        ),
      ),
    );
  });

  test('clear deletes the expiry even if the token delete fails', () async {
    final backing = FaultySecureStorage({_token: 't', _expiry: 'e'})
      ..failDeletesFor.add(_token);

    await expectLater(
      SessionStorage(backing).clear(),
      throwsA(isA<PlatformException>()),
    );
    expect(backing.values.containsKey(_expiry), isFalse);
  });

  test('unreadable token reads as logged out and is wiped', () async {
    final backing = FaultySecureStorage({_token: 't', _expiry: 'e'})
      ..failReadsFor.add(_token);

    expect(await SessionStorage(backing).readToken(), isNull);
    expect(backing.values, isEmpty);
  });

  group('email and validity (PIYA-212 AC1, AC5)', () {
    final before = DateTime.utc(2026, 10, 17);
    final after = DateTime.utc(2026, 11, 7);

    test('save stores the email so Settings needs no network', () async {
      final backing = FaultySecureStorage();
      final storage = SessionStorage(backing);
      await storage.save(testSession());

      expect(backing.values[_email], 'maria@example.com');
      expect(await storage.readEmail(), 'maria@example.com');
    });

    test('a failed token write rolls the email back too', () async {
      final backing = FaultySecureStorage()..failWritesFor.add(_token);
      await expectLater(
        SessionStorage(backing).save(testSession()),
        throwsA(isA<PlatformException>()),
      );
      expect(backing.values, isEmpty);
    });

    test('clear deletes the email', () async {
      final backing = FaultySecureStorage();
      final storage = SessionStorage(backing);
      await storage.save(testSession());
      await storage.clear();
      expect(backing.values, isEmpty);
    });

    test('an unreadable email reads as unknown, not a crash', () async {
      final backing = FaultySecureStorage({_email: 'x'})
        ..failReadsFor.add(_email);
      expect(await SessionStorage(backing).readEmail(), isNull);
    });

    test('valid only with a token and a future expiry', () async {
      final backing = FaultySecureStorage();
      final storage = SessionStorage(backing);
      expect(await storage.hasValidSession(now: before), isFalse);

      await storage.save(testSession());
      expect(await storage.hasValidSession(now: before), isTrue);
      expect(await storage.hasValidSession(now: after), isFalse);
    });

    test('a token without a parseable expiry is not a session', () async {
      final noExpiry = SessionStorage(FaultySecureStorage({_token: 't'}));
      expect(await noExpiry.hasValidSession(now: before), isFalse);

      final garbled = SessionStorage(
        FaultySecureStorage({_token: 't', _expiry: 'soon'}),
      );
      expect(await garbled.hasValidSession(now: before), isFalse);
    });

    test('an unreadable expiry is treated as logged out', () async {
      final backing = FaultySecureStorage({
        _token: 't',
        _expiry: '2026-11-06T00:00:00.000Z',
      })..failReadsFor.add(_expiry);
      expect(
        await SessionStorage(backing).hasValidSession(now: before),
        isFalse,
      );
    });
  });
}
