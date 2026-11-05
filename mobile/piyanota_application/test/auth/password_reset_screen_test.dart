import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart'
    show ProviderContainer, ProviderScope;
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/auth/auth_messages.dart';
import 'package:piyanota_application/screens/auth/login_screen.dart';
import 'package:piyanota_application/screens/auth/password_reset_screen.dart';
import 'package:piyanota_application/screens/auth/sign_up_screen.dart';
import 'package:piyanota_application/services/auth_api.dart';
import 'package:piyanota_application/services/fake_auth_api.dart';
import 'package:piyanota_application/state/resend_cooldowns.dart';
import 'package:piyanota_application/state/reset_code_waits.dart';

import 'auth_test_harness.dart';

const _sendCode = 'Send Code';
const _continue = 'Continue';
const _resetPassword = 'Reset Password';
const _email = 'maria@example.com';
const _code = '123456';
const _newPassword = 'choir2026';
const _demoCodePrefix = 'Your reset code is ';

Finder _field(int index) => find.byType(TextFormField).at(index);

/// Scrolls [label]'s button into view first, as a user would — with the
/// banner(s) and debug demo inbox above it, the CTA can sit below the fold.
Future<void> _tapButton(WidgetTester tester, String label) async {
  await tester.ensureVisible(buttonLabelled(label));
  await tester.pumpAndSettle();
  await tester.tap(buttonLabelled(label));
}

Future<void> _requestCode(WidgetTester tester, {String email = _email}) async {
  await tester.enterText(_field(0), email);
  await tester.pump();
  await _tapButton(tester, _sendCode);
  await tester.pumpAndSettle();
}

Future<void> _enterCode(WidgetTester tester, {String code = _code}) async {
  await tester.enterText(_field(0), code);
  await tester.pump();
  await _tapButton(tester, _continue);
  await tester.pumpAndSettle();
}

Future<void> _enterNewPassword(
  WidgetTester tester, {
  String password = _newPassword,
  String? confirm,
}) async {
  await tester.enterText(_field(0), password);
  await tester.enterText(_field(1), confirm ?? password);
  await tester.pump();
  await _tapButton(tester, _resetPassword);
  await tester.pump();
}

ScriptedAuthApi _happyApi() =>
    ScriptedAuthApi(onRequestReset: () async {}, onConfirmReset: () async {});

String _demoCode(WidgetTester tester) {
  final text = tester.widget<Text>(find.textContaining(_demoCodePrefix)).data!;
  return text.substring(_demoCodePrefix.length);
}

/// Moves the cooldown clock together with the widget tree's timers.
class _TestClock {
  DateTime now = DateTime(2026, 10, 28, 12);

  Override get override => resendClockProvider.overrideWithValue(() => now);

  Future<void> advance(WidgetTester tester, Duration by) async {
    now = now.add(by);
    await tester.pump(by);
  }
}

void main() {
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    // The work owner (review H1) lives in SharedPreferences.
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets(
    'AC1: Send Code disabled until the email is non-empty and well-formed',
    (tester) async {
      final api = _happyApi();
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: api,
      );

      expect(isButtonEnabled(tester, _sendCode), isFalse);
      for (final malformed in ['   ', 'maria', 'maria@', 'maria@example']) {
        await tester.enterText(_field(0), malformed);
        await tester.pump();
        expect(isButtonEnabled(tester, _sendCode), isFalse, reason: malformed);
      }

      // Keyboard "done" on a malformed email explains why, without a request.
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pump();
      expect(find.text(AuthMessages.emailInvalid), findsOneWidget);
      expect(api.requestResetCalls, 0);

      await tester.enterText(_field(0), _email);
      await tester.pump();
      expect(isButtonEnabled(tester, _sendCode), isTrue);
      expect(find.text(AuthMessages.emailInvalid), findsNothing);
    },
  );

  testWidgets('AC2: registered email shows the confirmation within 3 seconds', (
    tester,
  ) async {
    // Real fake latency (not zero), so the 3s budget is actually exercised.
    final api = FakeAuthApi();
    await pumpAuthScreen(tester, screen: const PasswordResetScreen(), api: api);

    await tester.enterText(_field(0), FakeAuthApi.demoEmail);
    await tester.pump();
    await tester.tap(buttonLabelled(_sendCode));
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    await tester.pump(const Duration(seconds: 3));
    expect(find.text(AuthMessages.resetCodeSent), findsOneWidget);
    expect(find.text('Enter Code'), findsOneWidget);
    // Debug demo inbox stands in for the email.
    expect(_demoCode(tester), matches(RegExp(r'^\d{6}$')));
  });

  testWidgets('V2.1 AC2: unregistered email shows the link message, no code', (
    tester,
  ) async {
    final api = FakeAuthApi(latency: Duration.zero);
    await pumpAuthScreen(tester, screen: const PasswordResetScreen(), api: api);

    await _requestCode(tester, email: 'nobody@example.com');

    expect(
      find.text(
        'Email has not yet been registered. Create a new account?',
        findRichText: true,
      ),
      findsOneWidget,
    );
    expect(find.text('Enter Code'), findsNothing);
    expect(find.text(AuthMessages.resetCodeSent), findsNothing);
    expect(api.demoInboxCodeFor('nobody@example.com'), isNull);
    // Only "Create a new account" is underlined.
    final root = tester
        .widget<RichText>(
          find.byWidgetPredicate(
            (w) =>
                w is RichText &&
                w.text.toPlainText().startsWith('Email has not yet'),
          ),
        )
        .text;
    final underlined = <String>[];
    root.visitChildren((span) {
      if (span is TextSpan &&
          span.style?.decoration == TextDecoration.underline) {
        underlined.add(span.text!);
      }
      return true;
    });
    expect(underlined, ['Create a new account']);
  });

  testWidgets(
    'V2.1 AC2: tapping the link opens Sign-Up with the email pre-filled; '
    'a screen reader can activate it',
    (tester) async {
      final handle = tester.ensureSemantics();
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: FakeAuthApi(latency: Duration.zero),
      );
      await _requestCode(tester, email: 'nobody@example.com');

      // TalkBack reaches the link through its own semantics node.
      final link = find.semantics.byLabel('Create a new account');
      final data = link.evaluate().single.getSemanticsData();
      expect(data.hasAction(SemanticsAction.tap), isTrue);
      expect(data.flagsCollection.isLink, isTrue);
      tester.semantics.tap(link);
      await tester.pumpAndSettle();
      expect(find.byType(SignUpScreen), findsOneWidget);
      expect(
        find.widgetWithText(TextFormField, 'nobody@example.com'),
        findsOneWidget,
      );
      handle.dispose();
    },
  );

  testWidgets('V2.1 AC1: registered email shows the exact new message', (
    tester,
  ) async {
    await pumpAuthScreen(
      tester,
      screen: const PasswordResetScreen(),
      api: FakeAuthApi(latency: Duration.zero),
    );
    await _requestCode(tester, email: FakeAuthApi.demoEmail);

    expect(
      find.text(
        'A reset code has been sent to this email. Please check your inbox.',
      ),
      findsOneWidget,
    );
    expect(find.text('Enter Code'), findsOneWidget);
  });

  testWidgets(
    'AC4: new password must meet the Sign-Up strength rule and match',
    (tester) async {
      final api = _happyApi();
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: api,
        stubLogin: true,
      );
      await _requestCode(tester);
      await _enterCode(tester);
      expect(find.text('New Password'), findsOneWidget);

      await _enterNewPassword(tester, password: 'short1', confirm: 'short1');
      expect(find.text(AuthMessages.passwordTooWeak), findsOneWidget);
      expect(api.confirmResetCalls, 0);

      await _enterNewPassword(tester, password: 'onlyletters');
      expect(find.text(AuthMessages.passwordTooWeak), findsOneWidget);
      expect(api.confirmResetCalls, 0);

      await _enterNewPassword(tester, confirm: 'choir2027');
      expect(find.text(AuthMessages.passwordTooWeak), findsNothing);
      expect(find.text(AuthMessages.passwordsDoNotMatch), findsOneWidget);
      expect(api.confirmResetCalls, 0);

      await _enterNewPassword(tester);
      await tester.pumpAndSettle();
      expect(api.confirmResetCalls, 1);
      expect(api.lastResetToken, _code);
      expect(api.lastNewPassword, _newPassword);
      // Opened with nothing underneath (e.g. a deep link): replaces to Login.
      expect(find.text(loginMarker), findsOneWidget);
    },
  );

  testWidgets(
    'AC5: success returns to the existing Login with a confirmation, and '
    'the new password works',
    (tester) async {
      final api = FakeAuthApi(latency: Duration.zero);
      await pumpAuthScreen(
        tester,
        screen: const LoginScreen(),
        api: api,
        extraRoutes: {
          AppRoutes.passwordReset: (_) => const PasswordResetScreen(),
        },
      );

      // A locked-out user resets the password: PIYA-202-V2.1 wait clears.
      await tester.enterText(_field(0), FakeAuthApi.demoEmail);
      await tester.enterText(_field(1), 'wrong-pass1');
      await tester.pump();
      // Four wrong passwords are free; the 5th starts the wait (J2).
      for (var i = 0; i < 5; i++) {
        await tester.tap(buttonLabelled('Log In'));
        await tester.pumpAndSettle();
      }
      expect(find.textContaining('Try again in'), findsOneWidget);

      await tester.tap(find.text('Forgot Password?'));
      await tester.pumpAndSettle();
      await _requestCode(tester, email: FakeAuthApi.demoEmail);
      await _enterCode(tester, code: _demoCode(tester));
      await _enterNewPassword(tester);
      await tester.pumpAndSettle();

      expect(find.byType(PasswordResetScreen), findsNothing);
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(find.text(AuthMessages.passwordResetSuccess), findsOneWidget);
      expect(
        find.widgetWithText(TextFormField, FakeAuthApi.demoEmail),
        findsOneWidget,
      );

      expect(find.textContaining('Try again in'), findsNothing);
      await tester.enterText(_field(1), _newPassword);
      await tester.pump();
      await tester.tap(buttonLabelled('Log In'));
      await tester.pumpAndSettle();
      expect(find.text(libraryMarker), findsOneWidget);
    },
  );

  testWidgets('AC5: Login shows the confirmation when reached by route', (
    tester,
  ) async {
    await pumpAuthScreen(
      tester,
      screen: const LoginScreen(passwordReset: PasswordResetSucceeded(_email)),
      api: ScriptedAuthApi(),
    );

    expect(find.text(AuthMessages.passwordResetSuccess), findsOneWidget);
    expect(find.widgetWithText(TextFormField, _email), findsOneWidget);
  });

  testWidgets('expired or used code (410) returns to the code step', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onRequestReset: () async {},
      onConfirmReset: () async => throw const ResetCodeInvalidException(),
    );
    await pumpAuthScreen(tester, screen: const PasswordResetScreen(), api: api);
    await _requestCode(tester);
    await _enterCode(tester);
    await _enterNewPassword(tester);
    await tester.pumpAndSettle();

    // B4.2: the confirm carries the email the code was requested for.
    expect(api.lastConfirmEmail, _email);
    expect(find.text('Enter Code'), findsOneWidget);
    expect(find.text(AuthMessages.resetCodeInvalid), findsOneWidget);
    expect(find.widgetWithText(TextFormField, _code), findsNothing);
    expect(isButtonEnabled(tester, _continue), isFalse);

    // Resend gets a fresh code and swaps the error for the confirmation.
    await tester.ensureVisible(find.widgetWithText(TextButton, 'Resend code'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, 'Resend code'));
    await tester.pumpAndSettle();
    expect(api.requestResetCalls, 2);
    expect(api.lastEmail, _email);
    expect(find.text(AuthMessages.resetCodeInvalid), findsNothing);
    expect(find.text(AuthMessages.resetCodeSent), findsOneWidget);
  });

  group('PIYA-204 reset request rate limit (B3)', () {
    testWidgets('a 429 on Send Code shows the wait, not the server error', (
      tester,
    ) async {
      final clock = _TestClock();
      final api = FakeAuthApi(latency: Duration.zero, clock: () => clock.now);
      // Each counts, registered or not (B3.1), so the next one is a 429.
      // Real async: the fake's delay would never fire under FakeAsync.
      await tester.runAsync(() async {
        for (var i = 0; i < FakeAuthApi.resetRequestMaxPerEmail; i++) {
          await api
              .requestPasswordReset(email: _email)
              .then((_) {}, onError: (_) {});
        }
      });
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: api,
        extraOverrides: [clock.override],
      );
      await _requestCode(tester);

      expect(find.text('Try again in 1:00:00'), findsOneWidget);
      expect(find.text(AuthMessages.serverError), findsNothing);
      expect(find.text('Enter Code'), findsNothing);
    });

    testWidgets('a 429 without a usable wait still says to wait', (
      tester,
    ) async {
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: ScriptedAuthApi(
          onRequestReset: () async => throw const AuthRateLimitedException(),
        ),
      );
      await _requestCode(tester);

      expect(find.text(AuthMessages.tooManyAttempts), findsOneWidget);
      expect(find.text(AuthMessages.serverError), findsNothing);
    });
  });

  group('PIYA-204-V2.4 wrong code and wait', () {
    Future<void> submitCode(WidgetTester tester, {bool first = false}) async {
      await _enterCode(tester);
      if (first) {
        await _enterNewPassword(tester);
      } else {
        await _tapButton(tester, _resetPassword);
        await tester.pump();
      }
      await tester.pumpAndSettle();
    }

    ScriptedAuthApi wrongApi({Object Function()? failure}) {
      return ScriptedAuthApi(
        onRequestReset: () async {},
        onConfirmReset: () async =>
            throw (failure?.call() ?? const ResetCodeWrongException()),
      );
    }

    testWidgets('AC1: wrong code shows its message and keeps the passwords', (
      tester,
    ) async {
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: wrongApi(),
      );
      await _requestCode(tester);
      await submitCode(tester, first: true);

      expect(
        find.text('Verification code is wrong. Try again.'),
        findsOneWidget,
      );
      expect(find.text('Enter Code'), findsOneWidget);
      expect(find.textContaining('Try again in'), findsNothing);

      await _enterCode(tester);
      expect(
        find.widgetWithText(TextFormField, _newPassword),
        findsNWidgets(2),
      );
    });

    testWidgets('AC2: wrong codes 1-2 have no wait, the 3rd starts 0:30', (
      tester,
    ) async {
      final clock = _TestClock();
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: wrongApi(),
        extraOverrides: [clock.override],
      );
      await _requestCode(tester);
      await submitCode(tester, first: true);
      expect(find.textContaining('Try again in'), findsNothing);
      await submitCode(tester);
      expect(find.textContaining('Try again in'), findsNothing);
      await submitCode(tester);

      expect(find.text('Try again in 0:30'), findsOneWidget);
      expect(find.text(AuthMessages.resetCodeWrong), findsOneWidget);
      await tester.enterText(_field(0), _code);
      await tester.pump();
      expect(isButtonEnabled(tester, _continue), isFalse);

      await clock.advance(tester, const Duration(seconds: 10));
      expect(find.text('Try again in 0:20'), findsOneWidget);
      await clock.advance(tester, const Duration(seconds: 20));
      expect(find.textContaining('Try again in'), findsNothing);
      expect(isButtonEnabled(tester, _continue), isTrue);

      // A further wrong code doubles the wait, and is still "wrong" (B4.4).
      await _tapButton(tester, _continue);
      await tester.pumpAndSettle();
      await _tapButton(tester, _resetPassword);
      await tester.pumpAndSettle();
      expect(find.text('Try again in 1:00'), findsOneWidget);
      expect(find.text(AuthMessages.resetCodeWrong), findsOneWidget);
    });

    test(
      'the wait after the 3rd, 4th and 5th wrong codes is 30, 60, 120 s',
      () {
        final clock = _TestClock();
        final container = ProviderContainer(overrides: [clock.override]);
        addTearDown(container.dispose);
        final waits = container.read(resetCodeWaitsProvider.notifier);
        waits.recordWrong(_email);
        waits.recordWrong(_email);
        expect(waits.remaining(_email), Duration.zero);
        for (final seconds in [30, 60, 120]) {
          waits.recordWrong(_email);
          expect(waits.remaining(_email), Duration(seconds: seconds));
        }
      },
    );

    testWidgets('AC2: the wait is announced at start and end', (tester) async {
      final announcements = <String>[];
      tester.binding.defaultBinaryMessenger
          .setMockDecodedMessageHandler<dynamic>(SystemChannels.accessibility, (
            message,
          ) async {
            if (message is Map && message['type'] == 'announce') {
              announcements.add((message['data'] as Map)['message'] as String);
            }
            return null;
          });
      addTearDown(
        () => tester.binding.defaultBinaryMessenger
            .setMockDecodedMessageHandler<dynamic>(
              SystemChannels.accessibility,
              null,
            ),
      );
      final clock = _TestClock();
      final handle = tester.ensureSemantics();
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: wrongApi(
          failure: () => const AuthRateLimitedException(retryAfterSeconds: 30),
        ),
        extraOverrides: [clock.override],
      );
      await _requestCode(tester);
      await submitCode(tester, first: true);

      expect(announcements, contains('Try again in 0:30'));
      expect(find.bySemanticsLabel('Try again in 0:30'), findsOneWidget);
      await clock.advance(tester, const Duration(seconds: 30));
      expect(announcements.last, AuthMessages.canTryAgain);
      handle.dispose();
    });

    testWidgets('AC3: an expired code keeps its own message and no wait', (
      tester,
    ) async {
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: wrongApi(failure: () => const ResetCodeInvalidException()),
      );
      await _requestCode(tester);
      await submitCode(tester, first: true);

      expect(find.text(AuthMessages.resetCodeInvalid), findsOneWidget);
      expect(find.text('Verification code is wrong. Try again.'), findsNothing);
      expect(find.textContaining('Try again in'), findsNothing);
    });

    testWidgets('AC4: a newly requested code resets the wrong-code count', (
      tester,
    ) async {
      final clock = _TestClock();
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: wrongApi(),
        extraOverrides: [clock.override],
      );
      await _requestCode(tester);
      await submitCode(tester, first: true);
      await submitCode(tester);
      await submitCode(tester);

      await clock.advance(tester, const Duration(seconds: 30));
      await tester.ensureVisible(
        find.widgetWithText(TextButton, 'Resend code'),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(TextButton, 'Resend code'));
      await tester.pumpAndSettle();

      // Two more wrong codes: still under the limit, so no wait.
      await submitCode(tester);
      await submitCode(tester);
      expect(find.textContaining('Try again in'), findsNothing);
    });

    testWidgets('AC4: a successful reset resets the count, per email', (
      tester,
    ) async {
      final api = ScriptedAuthApi(
        onRequestReset: () async {},
        onConfirmReset: () async {},
      );
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: api,
        stubLogin: true,
      );
      final container = ProviderScope.containerOf(
        tester.element(find.byType(PasswordResetScreen)),
      );
      final waits = container.read(resetCodeWaitsProvider.notifier);
      // Padding and case share one count.
      waits.recordWrong(' Maria@Example.com ');
      waits.recordWrong(_email);
      expect(waits.failures(_email), 2);
      expect(waits.failures('other@example.com'), 0);

      await _requestCode(tester);
      expect(waits.failures(_email), 0);

      waits.recordWrong(_email);
      await _enterCode(tester);
      await _enterNewPassword(tester);
      await tester.pumpAndSettle();
      expect(waits.failures(_email), 0);
    });

    for (final seconds in <int?>[null, 0]) {
      testWidgets('a 429 with retryAfterSeconds $seconds still shows a wait', (
        tester,
      ) async {
        final announcements = <String>[];
        tester.binding.defaultBinaryMessenger.setMockDecodedMessageHandler<
          dynamic
        >(SystemChannels.accessibility, (message) async {
          if (message is Map && message['type'] == 'announce') {
            announcements.add((message['data'] as Map)['message'] as String);
          }
          return null;
        });
        addTearDown(
          () => tester.binding.defaultBinaryMessenger
              .setMockDecodedMessageHandler<dynamic>(
                SystemChannels.accessibility,
                null,
              ),
        );
        await pumpAuthScreen(
          tester,
          screen: const PasswordResetScreen(),
          api: wrongApi(
            failure: () => AuthRateLimitedException(retryAfterSeconds: seconds),
          ),
        );
        await _requestCode(tester);
        await submitCode(tester, first: true);

        expect(find.text('Try again in 0:30'), findsOneWidget);
        expect(announcements, contains('Try again in 0:30'));
        await tester.enterText(_field(0), _code);
        await tester.pump();
        expect(isButtonEnabled(tester, _continue), isFalse);
      });
    }

    testWidgets('AC5: the server 429 retryAfterSeconds wins over our count', (
      tester,
    ) async {
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: wrongApi(
          failure: () => const AuthRateLimitedException(retryAfterSeconds: 90),
        ),
      );
      await _requestCode(tester);
      await submitCode(tester, first: true);

      expect(find.text('Try again in 1:30'), findsOneWidget);
    });

    testWidgets('a network failure is not counted as a wrong code', (
      tester,
    ) async {
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: wrongApi(failure: () => const AuthNetworkException()),
      );
      await _requestCode(tester);
      final container = ProviderScope.containerOf(
        tester.element(find.byType(PasswordResetScreen)),
      );
      await submitCode(tester, first: true);
      expect(
        container.read(resetCodeWaitsProvider.notifier).failures(_email),
        0,
      );
    });
  });

  testWidgets('Resend code is locked for 30 seconds after each send', (
    tester,
  ) async {
    final api = _happyApi();
    final clock = _TestClock();
    await pumpAuthScreen(
      tester,
      screen: const PasswordResetScreen(),
      api: api,
      extraOverrides: [clock.override],
    );
    await _requestCode(tester);

    Finder resend() => find.widgetWithText(TextButton, 'Resend code');
    TextButton lockedButton() => tester.widget<TextButton>(
      find.ancestor(
        of: find.textContaining('Resend code ('),
        matching: find.byType(TextButton),
      ),
    );

    expect(find.text('Resend code (30s)'), findsOneWidget);
    expect(lockedButton().onPressed, isNull);

    await clock.advance(tester, const Duration(seconds: 29));
    expect(find.text('Resend code (1s)'), findsOneWidget);
    expect(lockedButton().onPressed, isNull);

    await clock.advance(tester, const Duration(seconds: 1));
    expect(tester.widget<TextButton>(resend()).onPressed, isNotNull);

    await tester.ensureVisible(resend());
    await tester.pumpAndSettle();
    await tester.tap(resend());
    await tester.pump();
    expect(api.requestResetCalls, 2);
    expect(find.text('Resend code (30s)'), findsOneWidget);
  });

  group('PIYA-204-V2.2 resend countdown keyed by email', () {
    Future<void> goBackToEmail(WidgetTester tester) async {
      await tester.ensureVisible(find.text('Change email'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Change email'));
      await tester.pumpAndSettle();
    }

    testWidgets('AC1: same email again keeps remaining time, sends nothing', (
      tester,
    ) async {
      final api = _happyApi();
      final clock = _TestClock();
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: api,
        extraOverrides: [clock.override],
      );
      await _requestCode(tester);
      await clock.advance(tester, const Duration(seconds: 12));
      await goBackToEmail(tester);

      // Case and padding must not make it a "different" email.
      await _requestCode(tester, email: '  Maria@Example.com ');

      expect(api.requestResetCalls, 1);
      expect(find.text('Enter Code'), findsOneWidget);
      expect(find.text('Resend code (18s)'), findsOneWidget);
    });

    testWidgets('AC2: a different email gets a fresh send and its own 30 s', (
      tester,
    ) async {
      final api = _happyApi();
      final clock = _TestClock();
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: api,
        extraOverrides: [clock.override],
      );
      await _requestCode(tester);
      await clock.advance(tester, const Duration(seconds: 12));
      await goBackToEmail(tester);

      await _requestCode(tester, email: 'bea@example.com');

      expect(api.requestResetCalls, 2);
      expect(api.lastEmail, 'bea@example.com');
      expect(find.text('Resend code (30s)'), findsOneWidget);
    });

    testWidgets('AC3: countdown survives leaving and reopening the screen', (
      tester,
    ) async {
      final api = _happyApi();
      final clock = _TestClock();
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: api,
        extraOverrides: [clock.override],
      );
      await _requestCode(tester);
      await clock.advance(tester, const Duration(seconds: 10));

      // Same ProviderScope, new screen instance: the app is still open.
      tester
          .state<NavigatorState>(find.byType(Navigator))
          .pushReplacement(
            MaterialPageRoute<void>(
              builder: (_) => const PasswordResetScreen(),
            ),
          );
      await tester.pumpAndSettle();
      await _requestCode(tester);

      expect(api.requestResetCalls, 1);
      expect(find.text('Resend code (20s)'), findsOneWidget);
    });

    testWidgets('unregistered email starts no cooldown', (tester) async {
      final api = ScriptedAuthApi(
        onRequestReset: () async => throw const EmailNotRegisteredException(),
      );
      final clock = _TestClock();
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: api,
        extraOverrides: [clock.override],
      );
      await _requestCode(tester);
      await _requestCode(tester);

      expect(api.requestResetCalls, 2);
    });
  });

  testWidgets('server rejection of the new password keeps the user on it', (
    tester,
  ) async {
    const serverMessage = 'Password too common.';
    final api = ScriptedAuthApi(
      onRequestReset: () async {},
      onConfirmReset: () async =>
          throw const AuthValidationException(serverMessage),
    );
    await pumpAuthScreen(tester, screen: const PasswordResetScreen(), api: api);
    await _requestCode(tester);
    await _enterCode(tester);
    await _enterNewPassword(tester);
    await tester.pumpAndSettle();

    expect(find.text(serverMessage), findsOneWidget);
    expect(find.text('New Password'), findsOneWidget);
    expect(isButtonEnabled(tester, _resetPassword), isTrue);
  });

  testWidgets('server error on confirm shows the generic error, no hang', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onRequestReset: () async {},
      onConfirmReset: () async => throw const AuthServerException(),
    );
    await pumpAuthScreen(tester, screen: const PasswordResetScreen(), api: api);
    await _requestCode(tester);
    await _enterCode(tester);
    await _enterNewPassword(tester);
    await tester.pumpAndSettle();

    expect(find.text(AuthMessages.serverError), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.text('New Password'), findsOneWidget);
  });

  testWidgets('network failure is distinct and recoverable on both requests', (
    tester,
  ) async {
    var failRequest = true;
    final api = ScriptedAuthApi(
      onRequestReset: () async {
        if (failRequest) throw const AuthNetworkException();
      },
      onConfirmReset: () async => throw const AuthNetworkException(),
    );
    await pumpAuthScreen(tester, screen: const PasswordResetScreen(), api: api);

    await _requestCode(tester);
    expect(find.text(AuthMessages.network), findsOneWidget);
    expect(find.text(AuthMessages.resetCodeSent), findsNothing);
    expect(find.text(_sendCode), findsOneWidget); // still on step 1
    expect(isButtonEnabled(tester, _sendCode), isTrue);

    failRequest = false;
    await _tapButton(tester, _sendCode);
    await tester.pumpAndSettle();
    await _enterCode(tester);
    await _enterNewPassword(tester);
    await tester.pumpAndSettle();
    expect(find.text(AuthMessages.network), findsOneWidget);
    expect(find.text('New Password'), findsOneWidget);
    expect(isButtonEnabled(tester, _resetPassword), isTrue);
  });

  testWidgets('loading state shown and repeat submission blocked', (
    tester,
  ) async {
    final pendingRequest = Completer<void>();
    final pendingConfirm = Completer<void>();
    final api = ScriptedAuthApi(
      onRequestReset: () => pendingRequest.future,
      onConfirmReset: () => pendingConfirm.future,
    );
    await pumpAuthScreen(
      tester,
      screen: const PasswordResetScreen(),
      api: api,
      stubLogin: true,
    );

    await tester.enterText(_field(0), _email);
    await tester.pump();
    await tester.tap(buttonLabelled(_sendCode));
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    await tester.tap(find.byType(ElevatedButton));
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pump();
    expect(api.requestResetCalls, 1);
    pendingRequest.complete();
    await tester.pumpAndSettle();

    await _enterCode(tester);
    await _enterNewPassword(tester);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    await tester.tap(find.byType(ElevatedButton));
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pump();
    expect(api.confirmResetCalls, 1);
    pendingConfirm.complete();
    await tester.pumpAndSettle();
  });

  testWidgets('error banner clears once the user edits the field', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onRequestReset: () async => throw const AuthNetworkException(),
    );
    await pumpAuthScreen(tester, screen: const PasswordResetScreen(), api: api);

    await _requestCode(tester);
    expect(find.text(AuthMessages.network), findsOneWidget);
    await tester.enterText(_field(0), 'maria2@example.com');
    await tester.pump();
    expect(find.text(AuthMessages.network), findsNothing);
  });

  testWidgets('system back walks the steps back to Login, never exits', (
    tester,
  ) async {
    await pumpAuthScreen(
      tester,
      screen: const LoginScreen(),
      api: _happyApi(),
      extraRoutes: {
        AppRoutes.passwordReset: (_) => const PasswordResetScreen(),
      },
    );

    await tester.tap(find.text('Forgot Password?'));
    await tester.pumpAndSettle();
    await _requestCode(tester);
    await _enterCode(tester);
    expect(find.text('New Password'), findsOneWidget);

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('Enter Code'), findsOneWidget);

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.byType(TextFormField), findsOneWidget);
    expect(find.text(_sendCode), findsOneWidget);
    // The email the user typed survives stepping back.
    expect(find.widgetWithText(TextFormField, _email), findsOneWidget);

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.byType(PasswordResetScreen), findsNothing);
    expect(find.byType(LoginScreen), findsOneWidget);
    expect(find.text(AuthMessages.passwordResetSuccess), findsNothing);
  });

  testWidgets('NFR-10: every step fits a small screen at 2x text scale', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onRequestReset: () async {},
      onConfirmReset: () async => throw const AuthNetworkException(),
    );
    // 320x568 dp — the smallest common Android phone class.
    await pumpAuthScreen(
      tester,
      screen: const PasswordResetScreen(),
      api: api,
      physicalSize: const Size(640, 1136),
      textScale: 2.0,
    );
    tester.view.devicePixelRatio = 2.0;
    await tester.pump();

    await tester.enterText(_field(0), _email);
    await tester.ensureVisible(buttonLabelled(_sendCode));
    await tester.pumpAndSettle();
    await tester.tap(buttonLabelled(_sendCode));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);

    await tester.enterText(_field(0), _code);
    await tester.ensureVisible(buttonLabelled(_continue));
    await tester.pumpAndSettle();
    await tester.tap(buttonLabelled(_continue));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);

    await _enterNewPassword(tester);
    await tester.pumpAndSettle();
    expect(find.text(AuthMessages.network), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
