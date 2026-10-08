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
    final session = await api.login(
      email: 'new@example.com',
      password: 'secret123',
    );
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

  group('password reset (PIYA-303/304)', () {
    const newPassword = 'choir2026';

    Future<void> confirm(FakeAuthApi api, String code) =>
        api.confirmPasswordReset(
          resetToken: code,
          newPassword: newPassword,
          newPasswordConfirmation: newPassword,
        );

    test(
      'registered email gets a 6-digit code that resets the password',
      () async {
        final api = _api();
        await api.requestPasswordReset(email: ' Demo@PiyaNota.app ');
        final code = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;
        expect(code, matches(RegExp(r'^\d{6}$')));

        await confirm(api, code);

        final session = await api.login(
          email: FakeAuthApi.demoEmail,
          password: newPassword,
        );
        expect(session.email, FakeAuthApi.demoEmail);
        await expectLater(
          api.login(
            email: FakeAuthApi.demoEmail,
            password: FakeAuthApi.demoPassword,
          ),
          throwsA(isA<InvalidCredentialsException>()),
        );
      },
    );

    test(
      'unregistered email completes the same way but receives no code',
      () async {
        final api = _api();
        await api.requestPasswordReset(email: 'nobody@example.com');
        expect(api.demoInboxCodeFor('nobody@example.com'), isNull);
      },
    );

    test('malformed email is a 400; offline domain is a network failure', () {
      final api = _api();
      expect(
        api.requestPasswordReset(email: 'not-an-email'),
        throwsA(isA<AuthValidationException>()),
      );
      expect(
        api.requestPasswordReset(email: 'a@offline.test'),
        throwsA(isA<AuthNetworkException>()),
      );
    });

    test('code is single use (410 on reuse)', () async {
      final api = _api();
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      final code = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;
      await confirm(api, code);
      await expectLater(
        confirm(api, code),
        throwsA(isA<ResetCodeInvalidException>()),
      );
    });

    test('unknown code is a 410', () {
      expect(
        confirm(_api(), '000000'),
        throwsA(isA<ResetCodeInvalidException>()),
      );
    });

    test('code expires after resetCodeLifetime', () async {
      var now = DateTime.utc(2026, 10, 8, 9);
      final api = FakeAuthApi(latency: Duration.zero, clock: () => now);
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      final code = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;

      now = now.add(FakeAuthApi.resetCodeLifetime);
      expect(api.demoInboxCodeFor(FakeAuthApi.demoEmail), isNull);
      await expectLater(
        confirm(api, code),
        throwsA(isA<ResetCodeInvalidException>()),
      );
    });

    test('a new request invalidates the previous unused code', () async {
      final api = _api();
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      final first = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      final second = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;

      expect(second, isNot(first));
      await expectLater(
        confirm(api, first),
        throwsA(isA<ResetCodeInvalidException>()),
      );
      await confirm(api, second);
    });

    test('weak password is a 400 and does not consume the code', () async {
      final api = _api();
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      final code = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;

      await expectLater(
        api.confirmPasswordReset(
          resetToken: code,
          newPassword: 'short',
          newPasswordConfirmation: 'short',
        ),
        throwsA(isA<AuthValidationException>()),
      );
      await confirm(api, code);
    });
  });
}
