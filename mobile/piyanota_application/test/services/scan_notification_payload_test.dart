import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/services/scan_notification_payload.dart';

void main() {
  test('build and parse round-trip a string or int job id', () {
    expect(ScanNotificationPayload.build('a1b2-c3'), 'a1b2-c3');
    expect(ScanNotificationPayload.build(42), '42');
    expect(
      ScanNotificationPayload.parse(ScanNotificationPayload.build(42)),
      '42',
    );
    expect(
      ScanNotificationPayload.parse('3f2c1d9e-1111-4222-8333-444455556666'),
      '3f2c1d9e-1111-4222-8333-444455556666',
    );
  });

  test('a legacy payload that is just the id (with stray spaces) parses', () {
    expect(ScanNotificationPayload.parse(' job-7 '), 'job-7');
  });

  test('malformed or foreign payloads read as null', () {
    for (final bad in <Object?>[
      null,
      '',
      '   ',
      'https://piyanota.example/jobs/1?token=x',
      '{"jobId":"1"}',
      'job id',
      'a' * (ScanNotificationPayload.maxLength + 1),
      -1,
      3.5,
      <String>['1'],
    ]) {
      expect(ScanNotificationPayload.parse(bad), isNull, reason: '$bad');
      expect(ScanNotificationPayload.build(bad), isNull, reason: '$bad');
    }
  });
}
