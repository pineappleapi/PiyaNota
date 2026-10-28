import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/services/login_throttle.dart';

void main() {
  const email = 'demo@piyanota.app';
  final start = DateTime.utc(2026, 10, 28, 9);

  setUp(() => SharedPreferences.setMockInitialValues({}));

  // Wrong at start, wrong again [after] later: the wait the 2nd one earned.
  Future<Duration> secondWait(Duration after) async {
    final throttle = LoginThrottle(clock: () => start);
    await throttle.recordFailure(email);
    final later = start.add(after);
    await throttle.recordFailure(email, now: later);
    return throttle.remaining(email, now: later);
  }

  test(
    'PIYA-202-V2.1 AC8: 23 h 59 m after the last wrong try the count is kept',
    () async {
      expect(
        await secondWait(const Duration(hours: 23, minutes: 59)),
        const Duration(seconds: 60),
      );
    },
  );

  test(
    'PIYA-202-V2.1 AC8: at 24 h the count resets, first wait again',
    () async {
      expect(
        await secondWait(const Duration(hours: 24)),
        const Duration(seconds: 30),
      );
    },
  );

  test(
    'count saved by the previous app version (no timestamp) still reads',
    () async {
      SharedPreferences.setMockInitialValues({
        'login_throttle.failures.$email': 2,
      });
      final throttle = LoginThrottle(clock: () => start);
      await throttle.recordFailure(email);
      expect(await throttle.remaining(email), const Duration(seconds: 120));
    },
  );
}
