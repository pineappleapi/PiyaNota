import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/config/api_config.dart';

String? _check(String baseUrl, {bool fake = false, bool debug = false}) =>
    ApiConfig.configurationErrorFor(
      useFakeAuth: fake,
      baseUrl: baseUrl,
      allowCleartext: debug,
    );

void main() {
  test('fake backend defaults on only in debug builds', () {
    // Tests run in debug mode; profile/release get the false default.
    expect(kDebugMode, isTrue);
    expect(ApiConfig.useFakeAuth, kDebugMode);
  });

  test('fake backend needs no URL', () {
    expect(_check('', fake: true), isNull);
  });

  test('real backend without a URL is rejected', () {
    expect(_check(''), contains('API_BASE_URL'));
  });

  test('relative or host-less URL is rejected', () {
    expect(_check('/api'), contains('absolute'));
    expect(_check('api.example.com'), contains('absolute'));
  });

  test('https is required outside debug (FR-17 / NFR-7)', () {
    expect(_check('http://192.168.1.20:5000'), contains('https'));
    expect(_check('https://api.example.com'), isNull);
  });

  test('cleartext allowed in debug for a local server', () {
    expect(_check('http://10.0.2.2:5000', debug: true), isNull);
  });
}
