import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/services/session_storage.dart';

import 'auth_test_harness.dart';

const _token = 'session_token';
const _expiry = 'session_expires_at';

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
        isA<PlatformException>()
            .having((e) => e.code, 'code', 'test-write-failed'),
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
}
