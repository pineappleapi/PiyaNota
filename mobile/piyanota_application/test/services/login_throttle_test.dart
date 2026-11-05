import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/services/login_throttle.dart';

void main() {
  const email = 'demo@piyanota.app';
  final start = DateTime.utc(2026, 10, 28, 9);

  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('a stored server wait counts down and clears at expiry', () async {
    var now = start;
    final throttle = LoginThrottle(clock: () => now);
    await throttle.recordServerWait(email, const Duration(seconds: 30));
    now = start.add(const Duration(seconds: 29));
    expect(await throttle.remaining(email), const Duration(seconds: 1));
    now = start.add(const Duration(seconds: 30));
    expect(await throttle.remaining(email), Duration.zero);
  });

  test('an hour-long wait is kept whole', () async {
    final throttle = LoginThrottle(clock: () => start);
    await throttle.recordServerWait(email, const Duration(hours: 1));
    expect(await throttle.remaining(email), const Duration(hours: 1));
  });

  test('waits are per email, case-insensitively, and reset clears', () async {
    final throttle = LoginThrottle(clock: () => start);
    await throttle.recordServerWait(email, const Duration(seconds: 30));
    expect(
      await throttle.remaining(' DEMO@piyanota.app '),
      const Duration(seconds: 30),
    );
    expect(await throttle.remaining('other@example.com'), Duration.zero);
    await throttle.reset(email);
    expect(await throttle.remaining(email), Duration.zero);
  });
}
