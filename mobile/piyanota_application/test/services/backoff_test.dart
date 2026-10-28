import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/services/backoff.dart';

void main() {
  test('no failures means no wait', () {
    expect(backoffAfter(0), Duration.zero);
  });

  test('starts at 30 s and doubles', () {
    const expected = [30, 60, 120, 240, 480];
    for (var i = 0; i < expected.length; i++) {
      expect(backoffAfter(i + 1), Duration(seconds: expected[i]));
    }
  });

  test('caps at 15 min without overflowing', () {
    for (final failures in [6, 7, 50, 1000]) {
      expect(backoffAfter(failures), const Duration(seconds: 900));
    }
  });
}
