import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/state/resend_cooldowns.dart';
import 'package:piyanota_application/state/reset_code_waits.dart';

void main() {
  const email = 'demo@piyanota.app';
  var now = DateTime.utc(2026, 10, 28, 9);

  ResetCodeWaits make() {
    now = DateTime.utc(2026, 10, 28, 9);
    final container = ProviderContainer(
      overrides: [resendClockProvider.overrideWithValue(() => now)],
    );
    addTearDown(container.dispose);
    return container.read(resetCodeWaitsProvider.notifier);
  }

  test(
    'PIYA-204-V2.4 AC6: 23 h 59 m after the last wrong code the count is kept',
    () {
      final waits = make();
      for (var i = 0; i < 3; i++) {
        waits.recordWrong(email);
      }
      now = now.add(const Duration(hours: 23, minutes: 59));
      waits.recordWrong(email);
      expect(waits.failures(email), 4);
      expect(waits.remaining(email), const Duration(seconds: 60));
    },
  );

  test(
    'PIYA-204-V2.4 AC6: at 24 h the count resets, 2 more are free again',
    () {
      final waits = make();
      for (var i = 0; i < 3; i++) {
        waits.recordWrong(email);
      }
      now = now.add(const Duration(hours: 24));
      waits.recordWrong(email);
      expect(waits.failures(email), 1);
      expect(waits.remaining(email), Duration.zero);
      waits.recordWrong(email);
      waits.recordWrong(email);
      expect(waits.remaining(email), const Duration(seconds: 30));
    },
  );
}
