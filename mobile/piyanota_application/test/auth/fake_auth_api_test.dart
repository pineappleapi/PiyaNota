import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/services/auth_api.dart';
import 'package:piyanota_application/services/fake_auth_api.dart';

FakeAuthApi _api() => FakeAuthApi(latency: Duration.zero);

void main() {
  test('demo credentials log in, case-insensitively on email', () async {
    final session = await _api().login(
      email: '  Demo@PiyaNota.app ',
      password: FakeAuthApi.demoPassword,
    );
    expect(session.email, FakeAuthApi.demoEmail);
    expect(session.sessionToken, isNotEmpty);
    expect(session.expiresAt.isAfter(DateTime.now().toUtc()), isTrue);
  });

  test('wrong password is a 401', () {
    expect(
      _api().login(email: FakeAuthApi.demoEmail, password: 'nope1234'),
      throwsA(isA<InvalidCredentialsException>()),
    );
  });

  test('offline domain simulates a network failure', () {
    expect(
      _api().login(email: 'a@offline.test', password: 'x'),
      throwsA(isA<AuthNetworkException>()),
    );
  });

  test('sign-up then login with the new account', () async {
    final api = _api();
    await api.signUp(
      email: 'new@example.com',
      password: 'secret123',
      passwordConfirmation: 'secret123',
    );
    final session =
        await api.login(email: 'new@example.com', password: 'secret123');
    expect(session.email, 'new@example.com');
  });

  test('registered email is a 409', () {
    expect(
      _api().signUp(
        email: 'DEMO@piyanota.app',
        password: 'secret123',
        passwordConfirmation: 'secret123',
      ),
      throwsA(isA<EmailAlreadyRegisteredException>()),
    );
  });

  test('weak or mismatched password is a 400', () {
    final api = _api();
    expect(
      api.signUp(
        email: 'a@example.com',
        password: 'short',
        passwordConfirmation: 'short',
      ),
      throwsA(isA<AuthValidationException>()),
    );
    expect(
      api.signUp(
        email: 'b@example.com',
        password: 'secret123',
        passwordConfirmation: 'secret124',
      ),
      throwsA(isA<AuthValidationException>()),
    );
  });
}
