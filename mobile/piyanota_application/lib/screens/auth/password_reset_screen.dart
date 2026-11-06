import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../config/api_config.dart';
import '../../routes/app_routes.dart';
import '../../services/auth_api.dart';
import '../../services/auth_validators.dart';
import '../../services/backoff.dart';
import '../../services/fake_auth_api.dart';
import '../../state/auth_providers.dart';
import '../../state/resend_cooldowns.dart';
import '../../state/reset_code_waits.dart';
import '../../theme/app_theme.dart';
import '../../widgets/primary_pill_button.dart';
import 'auth_messages.dart';
import 'sign_up_screen.dart';
import 'widgets/auth_error_banner.dart';
import 'widgets/auth_scaffold.dart';
import 'widgets/auth_switch_prompt.dart';
import 'widgets/auth_text_field.dart';

/// Route result handed back to Login when the reset completes, so Login can
/// show the PIYA-204 AC5 confirmation and prefill the email.
class PasswordResetSucceeded {
  const PasswordResetSucceeded(this.email);

  final String email;
}

enum _ResetStep { email, code, newPassword }

/// PIYA-204 — Password Reset UI: email → emailed code → new password.
///
/// One route with internal steps rather than three pushed routes, so that
/// on success a single pop lands on the Login underneath (no stacked
/// Logins), and system back walks the steps in reverse instead of
/// abandoning a half-finished reset.
///
/// The code is checked on the Enter Code step by the verify endpoint (J1/B1),
/// so only a code the server accepted reaches the new-password step. Confirm
/// still re-checks it, since the server never trusts the earlier call.
class PasswordResetScreen extends ConsumerStatefulWidget {
  const PasswordResetScreen({super.key});

  @override
  ConsumerState<PasswordResetScreen> createState() =>
      _PasswordResetScreenState();
}

class _PasswordResetScreenState extends ConsumerState<PasswordResetScreen> {
  final _emailFormKey = GlobalKey<FormState>();
  final _passwordFormKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _codeController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmController = TextEditingController();

  _ResetStep _step = _ResetStep.email;
  bool _isSubmitting = false;
  // Format errors stay hidden until the user tries to submit (keyboard
  // action or tap), then track keystrokes — same rule as Sign-Up.
  bool _emailSubmitAttempted = false;
  bool _passwordSubmitAttempted = false;
  String? _errorMessage;
  String? _noticeMessage;

  /// PIYA-204-V2.1: set when the server said the email has no account;
  /// shows the message with the Sign-Up link instead of an error string.
  bool _emailNotRegistered = false;

  /// Owned here, not built in `build`, so it can be disposed.
  final TapGestureRecognizer _createAccountTap = TapGestureRecognizer();

  /// The email the current code was requested for — fixed at request time
  /// so editing the (hidden) email field can't change what Login receives.
  String _requestedEmail = '';

  /// Last-seen text per controller. Listeners also fire on cursor moves,
  /// so only a real text change may clear a stale error banner. Filled in
  /// initState, before any listener fires — a lazy initializer would first
  /// run inside the first listener call, after the text already changed,
  /// and miss that edit.
  final Map<TextEditingController, String> _lastTexts = {};

  /// Only repaints once a second; the time itself lives in
  /// [resendCooldownsProvider], keyed by email (PIYA-204-V2.2).
  Timer? _resendCooldownTimer;

  /// PIYA-204-V2.4: repaints the wrong-code countdown once a second. The
  /// time itself lives in [resetCodeWaitsProvider], keyed by email.
  Timer? _waitTimer;

  static const double _fieldGap = 16;
  static const double _sectionGap = 24;

  // Each send invalidates the previous code (PIYA-303 AC5), so rapid
  // resends let an older email arrive last and carry a dead code. The
  // cooldown also stops one device spamming reset emails; server-side
  // rate limiting is still needed (BUG-049).
  static const Duration _cooldownTick = Duration(seconds: 1);

  List<TextEditingController> get _controllers => [
    _emailController,
    _codeController,
    _passwordController,
    _confirmController,
  ];

  @override
  void initState() {
    super.initState();
    _createAccountTap.onTap = _openSignUp;
    for (final controller in _controllers) {
      _lastTexts[controller] = controller.text;
      controller.addListener(() => _onFieldChanged(controller));
    }
  }

  @override
  void dispose() {
    _resendCooldownTimer?.cancel();
    _waitTimer?.cancel();
    _createAccountTap.dispose();
    for (final controller in _controllers) {
      controller.dispose();
    }
    super.dispose();
  }

  void _onFieldChanged(TextEditingController controller) {
    final textChanged = _lastTexts[controller] != controller.text;
    _lastTexts[controller] = controller.text;
    setState(() {
      // The banner described the input as it was at submit time; once the
      // user edits, it's stale and would contradict what they now see.
      if (textChanged && !_isSubmitting) {
        _errorMessage = null;
        _emailNotRegistered = false;
      }
    });
  }

  /// Seconds until "Resend code" unlocks again; 0 means available.
  int get _resendCooldownLeft =>
      ref.read(resendCooldownsProvider.notifier).secondsLeft(_requestedEmail);

  /// Repaints each second until the stored deadline passes.
  void _tickResendCooldown() {
    _resendCooldownTimer?.cancel();
    if (_resendCooldownLeft <= 0) return;
    _resendCooldownTimer = Timer.periodic(_cooldownTick, (timer) {
      if (!mounted) return;
      setState(() {
        if (_resendCooldownLeft <= 0) timer.cancel();
      });
    });
  }

  /// Time left before the code may be tried again; zero when free.
  Duration get _wait =>
      ref.read(resetCodeWaitsProvider.notifier).remaining(_requestedEmail);

  /// Repaints each second until the stored deadline passes. Spoken once at
  /// the start and once at the end; the visible countdown is not a live
  /// region, or TalkBack would read every tick, and a focused read still
  /// gets the current value because the Text stays in semantics.
  void _tickWait({bool announce = false}) {
    _waitTimer?.cancel();
    if (_wait == Duration.zero) return;
    if (announce) _announce(AuthMessages.tryAgainIn(_wait));
    _waitTimer = Timer.periodic(_cooldownTick, (timer) {
      if (!mounted) return;
      final done = _wait == Duration.zero;
      setState(() {});
      if (done) {
        timer.cancel();
        _announce(AuthMessages.canTryAgain);
      }
    });
  }

  void _announce(String message) {
    SemanticsService.sendAnnouncement(
      View.of(context),
      message,
      Directionality.of(context),
    );
  }

  void _stopResendCooldown() {
    _resendCooldownTimer?.cancel();
    ref.read(resendCooldownsProvider.notifier).clear(_requestedEmail);
  }

  String get _code => _codeController.text.trim();

  // AC1: Submit disabled until non-empty *and* well-formatted.
  bool get _canRequestCode =>
      !_isSubmitting && AuthValidators.isValidEmail(_emailController.text);

  // V2.4 AC2: typing stays allowed during the wait; only submitting is not.
  bool get _canContinueWithCode =>
      !_isSubmitting &&
      _wait == Duration.zero &&
      AuthValidators.isWellFormedResetCode(_code);

  bool get _canResetPassword =>
      !_isSubmitting &&
      _wait == Duration.zero &&
      _passwordController.text.isNotEmpty &&
      _confirmController.text.isNotEmpty;

  String? _validateEmail(String? value) {
    final email = value?.trim() ?? '';
    if (email.isEmpty) return AuthMessages.emailRequired;
    if (!AuthValidators.isValidEmail(email)) return AuthMessages.emailInvalid;
    return null;
  }

  String? _validatePassword(String? value) =>
      AuthValidators.meetsPasswordPolicy(value ?? '')
      ? null
      : AuthMessages.passwordTooWeak;

  String? _validateConfirmation(String? value) =>
      value == _passwordController.text
      ? null
      : AuthMessages.passwordsDoNotMatch;

  void _onEmailKeyboardSubmit() {
    if (_canRequestCode) {
      _requestCode();
      return;
    }
    // Disabled button + keyboard "done" on a malformed email: say why.
    setState(() => _emailSubmitAttempted = true);
  }

  /// Used for both the first request and "Resend code".
  Future<void> _requestCode() async {
    final email = _step == _ResetStep.email
        ? _emailController.text.trim()
        : _requestedEmail;
    if (_isSubmitting || !AuthValidators.isValidEmail(email)) return;
    // V2.2: a code for this email is still cooling down, so it is still the
    // live one; going back and resubmitting must not send another.
    if (_step == _ResetStep.email &&
        ref.read(resendCooldownsProvider.notifier).secondsLeft(email) > 0) {
      setState(() {
        _requestedEmail = email;
        _errorMessage = null;
        _emailNotRegistered = false;
        _noticeMessage = AuthMessages.resetCodeSent;
        _step = _ResetStep.code;
        _tickResendCooldown();
        _tickWait();
      });
      return;
    }
    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
      _noticeMessage = null;
      _emailNotRegistered = false;
    });

    String? error;
    var unregistered = false;
    try {
      await ref.read(authApiProvider).requestPasswordReset(email: email);
    } on EmailNotRegisteredException {
      unregistered = true;
    } on AuthRateLimitedException catch (e) {
      // B3.2: too many requests for this email. Not the code-step wait,
      // which would lock Continue for a limit on sending, not on codes.
      final seconds = e.retryAfterSeconds;
      error = seconds != null && seconds > 0
          ? AuthMessages.tryAgainIn(Duration(seconds: seconds))
          : AuthMessages.tooManyAttempts;
    } on AuthNetworkException {
      error = AuthMessages.network;
    } on AuthValidationException catch (e) {
      error = e.serverMessage ?? AuthMessages.emailInvalid;
    } on AuthException {
      error = AuthMessages.serverError;
    } catch (e, stack) {
      // See LoginScreen._submit: never leave the button stuck loading.
      debugPrint('Password reset request failed unexpectedly: $e\n$stack');
      error = AuthMessages.serverError;
    }

    if (!mounted) return;
    // Cleared while _isSubmitting is still true, so its change listener
    // doesn't treat this programmatic edit as the user's.
    if (error == null && !unregistered) _codeController.clear();
    setState(() {
      _isSubmitting = false;
      if (unregistered) {
        _emailNotRegistered = true;
        return;
      }
      if (error != null) {
        _errorMessage = error;
        return;
      }
      _requestedEmail = email;
      _noticeMessage = AuthMessages.resetCodeSent;
      _step = _ResetStep.code;
      // Only a real send starts a cooldown: an unregistered email returned
      // above sends no code.
      ref.read(resendCooldownsProvider.notifier).recordSent(email);
      // V2.4 AC4: a new code starts the wrong-code count afresh.
      ref.read(resetCodeWaitsProvider.notifier).reset(email);
      _tickResendCooldown();
      _tickWait();
    });
  }

  /// Pushed as a typed route (not a named one) so the email travels as a
  /// constructor argument. Back returns here with the message still shown.
  void _openSignUp() {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) =>
            SignUpScreen(initialEmail: _emailController.text.trim()),
      ),
    );
  }

  /// The server's wait replaces our own count (V2.4 AC5). A wait without
  /// seconds is still a wait, but not a wrong code (B4.5), so the count stays.
  void _recordServerWait(AuthRateLimitedException e) {
    final seconds = e.retryAfterSeconds;
    final waits = ref.read(resetCodeWaitsProvider.notifier);
    if (seconds != null && seconds > 0) {
      waits.recordServerWait(_requestedEmail, Duration(seconds: seconds));
      return;
    }
    waits.recordServerWait(
      _requestedEmail,
      backoffAfter(
        math.max(1, waits.failures(_requestedEmail) - resetCodeFreeAttempts),
      ),
    );
  }

  /// Counts the wrong code; from the 5th on the server's own wait, when it
  /// sent one, overrides our mirror of the ladder.
  void _recordWrongCode(ResetCodeWrongException e) {
    final waits = ref.read(resetCodeWaitsProvider.notifier)
      ..recordWrong(_requestedEmail);
    final seconds = e.retryAfterSeconds;
    if (seconds != null && seconds > 0) {
      waits.recordServerWait(_requestedEmail, Duration(seconds: seconds));
    }
  }

  /// Only a 200 from verify moves on; every failure stays on Enter Code with
  /// the typed passwords untouched.
  Future<void> _continueWithCode() async {
    if (!_canContinueWithCode) return;
    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
      _noticeMessage = null;
    });

    String? error;
    var wrongCode = false;
    var expired = false;
    var waiting = false;
    try {
      await ref
          .read(authApiProvider)
          .verifyPasswordReset(email: _requestedEmail, code: _code);
    } on ResetCodeInvalidException {
      error = AuthMessages.resetCodeInvalid;
      expired = true;
    } on ResetCodeWrongException catch (e) {
      error = AuthMessages.resetCodeWrong;
      wrongCode = true;
      _recordWrongCode(e);
    } on AuthRateLimitedException catch (e) {
      waiting = true;
      _recordServerWait(e);
    } on AuthNetworkException {
      error = AuthMessages.network;
    } on AuthException {
      error = AuthMessages.serverError;
    } catch (e, stack) {
      debugPrint('Password reset verify failed unexpectedly: $e\n$stack');
      error = AuthMessages.serverError;
    }

    if (!mounted) return;
    // Cleared while _isSubmitting is still true, so the change listener
    // doesn't wipe the new error.
    if (wrongCode || expired) _codeController.clear();
    setState(() {
      _isSubmitting = false;
      // An expired code is dead; Resend must be usable at once.
      if (expired) _stopResendCooldown();
      _errorMessage = error;
      if (error == null && !waiting) _step = _ResetStep.newPassword;
      _tickWait(announce: wrongCode || waiting);
    });
  }

  Future<void> _resetPassword() async {
    if (!_canResetPassword) return;
    setState(() => _passwordSubmitAttempted = true);
    final form = _passwordFormKey.currentState;
    // AC4: same strength rule as Sign-Up, checked before any request.
    if (form == null || !form.validate()) return;

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });

    String? error;
    var codeRejected = false;
    var waiting = false;
    var wrongCode = false;
    try {
      await ref
          .read(authApiProvider)
          .confirmPasswordReset(
            email: _requestedEmail,
            resetToken: _code,
            newPassword: _passwordController.text,
            newPasswordConfirmation: _confirmController.text,
          );
    } on ResetCodeInvalidException {
      error = AuthMessages.resetCodeInvalid;
      codeRejected = true;
    } on ResetCodeWrongException catch (e) {
      // The reset is still alive, so unlike an expired code it keeps its
      // resend cooldown; only the typed code is wrong.
      error = AuthMessages.resetCodeWrong;
      codeRejected = true;
      wrongCode = true;
      _recordWrongCode(e);
    } on AuthRateLimitedException catch (e) {
      waiting = true;
      _recordServerWait(e);
    } on AuthNetworkException {
      error = AuthMessages.network;
    } on AuthValidationException catch (e) {
      error = e.serverMessage ?? AuthMessages.validationFallback;
    } on AuthException {
      error = AuthMessages.serverError;
    } catch (e, stack) {
      debugPrint('Password reset confirm failed unexpectedly: $e\n$stack');
      error = AuthMessages.serverError;
    }

    if (!mounted) return;
    if (error == null && !waiting) {
      // The code is spent, so a later reset for this email must send anew.
      _stopResendCooldown();
      ref.read(resetCodeWaitsProvider.notifier).reset(_requestedEmail);
      _finish();
      return;
    }
    // The code, not the password, is what needs fixing — take the user to
    // where they can enter or resend one. The typed passwords are kept so a
    // corrected code doesn't mean retyping them. Cleared before
    // _isSubmitting drops so the listener doesn't wipe the new error.
    if (codeRejected) _codeController.clear();
    setState(() {
      _isSubmitting = false;
      if (codeRejected || waiting) _step = _ResetStep.code;
      // An expired code is dead; a new one is the only way forward.
      if (codeRejected && !wrongCode) _stopResendCooldown();
      _errorMessage = error;
      _tickWait(announce: wrongCode || waiting);
    });
  }

  /// AC5: back to the existing Login (the screen is pushed over it from
  /// "Forgot Password?") carrying the success, rather than stacking a new
  /// Login on top.
  void _finish() {
    final result = PasswordResetSucceeded(_requestedEmail);
    final navigator = Navigator.of(context);
    if (navigator.canPop()) {
      navigator.pop(result);
    } else {
      navigator.pushReplacementNamed(AppRoutes.login, arguments: result);
    }
  }

  void _goToLogin() {
    final navigator = Navigator.of(context);
    if (navigator.canPop()) {
      navigator.pop();
    } else {
      navigator.pushReplacementNamed(AppRoutes.login);
    }
  }

  void _goBackAStep() {
    if (_isSubmitting) return;
    switch (_step) {
      case _ResetStep.email:
        _goToLogin();
      case _ResetStep.code:
        setState(() {
          _errorMessage = null;
          _noticeMessage = null;
          _step = _ResetStep.email;
        });
      case _ResetStep.newPassword:
        setState(() {
          _errorMessage = null;
          _step = _ResetStep.code;
        });
    }
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop:
          _step == _ResetStep.email &&
          !_isSubmitting &&
          Navigator.of(context).canPop(),
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _goBackAStep();
      },
      child: AuthScaffold(
        headline: switch (_step) {
          _ResetStep.email => 'Forgot your password?',
          _ResetStep.code => 'Check your email',
          _ResetStep.newPassword => 'Almost there!',
        },
        accentHeadline: switch (_step) {
          _ResetStep.email => "We'll help you get\nback to rehearsing.",
          _ResetStep.code => 'Enter the code to\nreset your password.',
          _ResetStep.newPassword => 'Choose a new\npassword.',
        },
        title: switch (_step) {
          _ResetStep.email => 'Forgot Password',
          _ResetStep.code => 'Enter Code',
          _ResetStep.newPassword => 'New Password',
        },
        switchPrompt: AuthSwitchPrompt(
          prompt: 'Remembered your password?',
          actionLabel: 'Log In',
          onPressed: _isSubmitting ? null : _goToLogin,
        ),
        children: [
          ..._banners(),
          ...switch (_step) {
            _ResetStep.email => _emailStep(),
            _ResetStep.code => _codeStep(),
            _ResetStep.newPassword => _newPasswordStep(),
          },
        ],
      ),
    );
  }

  List<Widget> _banners() {
    final error = _errorMessage;
    final notice = _noticeMessage;
    return [
      if (notice != null) ...[
        AuthNoticeBanner(message: notice),
        const SizedBox(height: _fieldGap),
      ],
      if (_emailNotRegistered) ...[
        AuthErrorBanner(
          message:
              '${AuthMessages.emailNotRegistered}'
              '${AuthMessages.createNewAccount}'
              '${AuthMessages.emailNotRegisteredEnd}',
          messageSpans: [
            const TextSpan(text: AuthMessages.emailNotRegistered),
            TextSpan(
              text: AuthMessages.createNewAccount,
              recognizer: _createAccountTap,
              style: const TextStyle(
                decoration: TextDecoration.underline,
                fontWeight: FontWeight.w700,
              ),
            ),
            const TextSpan(text: AuthMessages.emailNotRegisteredEnd),
          ],
        ),
        const SizedBox(height: _fieldGap),
      ],
      if (error != null) ...[
        AuthErrorBanner(message: error),
        const SizedBox(height: _fieldGap),
      ],
    ];
  }

  List<Widget> _emailStep() {
    return [
      Form(
        key: _emailFormKey,
        autovalidateMode: _emailSubmitAttempted
            ? AutovalidateMode.always
            : AutovalidateMode.disabled,
        child: AuthTextField(
          controller: _emailController,
          hintText: 'Enter your email address',
          icon: Icons.mail_outline_rounded,
          keyboardType: TextInputType.emailAddress,
          textInputAction: TextInputAction.done,
          autofillHints: const [AutofillHints.email],
          enabled: !_isSubmitting,
          validator: _validateEmail,
          helperText: "We'll email you a 6-digit code to reset your password.",
          onFieldSubmitted: (_) => _onEmailKeyboardSubmit(),
        ),
      ),
      const SizedBox(height: _sectionGap),
      PrimaryPillButton(
        label: 'Send Code',
        onPressed: _canRequestCode ? _requestCode : null,
        isLoading: _isSubmitting,
      ),
    ];
  }

  List<Widget> _waitNotice() {
    final wait = _wait;
    if (wait == Duration.zero) return const [];
    return [
      const SizedBox(height: _fieldGap),
      Text(
        AuthMessages.tryAgainIn(wait),
        textAlign: TextAlign.center,
        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
          color: AppTheme.authSubtitle,
          fontWeight: FontWeight.w600,
        ),
      ),
    ];
  }

  List<Widget> _codeStep() {
    return [
      if (ApiConfig.useFakeAuth) ...[
        _DemoInbox(email: _requestedEmail),
        const SizedBox(height: _fieldGap),
      ],
      AuthTextField(
        controller: _codeController,
        hintText: 'Enter 6-digit code',
        icon: Icons.pin_outlined,
        keyboardType: TextInputType.number,
        textInputAction: TextInputAction.done,
        autofillHints: const [AutofillHints.oneTimeCode],
        inputFormatters: [
          FilteringTextInputFormatter.digitsOnly,
          LengthLimitingTextInputFormatter(AuthValidators.resetCodeLength),
        ],
        enabled: !_isSubmitting,
        helperText: 'Code requested for $_requestedEmail',
        onFieldSubmitted: (_) => _continueWithCode(),
      ),
      Wrap(
        alignment: WrapAlignment.spaceBetween,
        children: [
          _LinkButton(
            label: 'Change email',
            onPressed: _isSubmitting ? null : _goBackAStep,
          ),
          _LinkButton(
            label: _resendCooldownLeft > 0
                ? 'Resend code (${_resendCooldownLeft}s)'
                : 'Resend code',
            onPressed: _isSubmitting || _resendCooldownLeft > 0
                ? null
                : _requestCode,
          ),
        ],
      ),
      ..._waitNotice(),
      const SizedBox(height: _sectionGap),
      PrimaryPillButton(
        label: 'Continue',
        onPressed: _canContinueWithCode ? _continueWithCode : null,
        isLoading: _isSubmitting,
      ),
    ];
  }

  List<Widget> _newPasswordStep() {
    return [
      Form(
        key: _passwordFormKey,
        autovalidateMode: _passwordSubmitAttempted
            ? AutovalidateMode.always
            : AutovalidateMode.disabled,
        child: AutofillGroup(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              AuthPasswordField(
                controller: _passwordController,
                hintText: 'New password',
                textInputAction: TextInputAction.next,
                autofillHints: const [AutofillHints.newPassword],
                enabled: !_isSubmitting,
                validator: _validatePassword,
                helperText: AuthValidators.passwordPolicyDescription,
              ),
              const SizedBox(height: _fieldGap),
              AuthPasswordField(
                controller: _confirmController,
                hintText: 'Confirm new password',
                textInputAction: TextInputAction.done,
                autofillHints: const [AutofillHints.newPassword],
                enabled: !_isSubmitting,
                validator: _validateConfirmation,
                onFieldSubmitted: (_) => _resetPassword(),
              ),
            ],
          ),
        ),
      ),
      ..._waitNotice(),
      const SizedBox(height: _sectionGap),
      PrimaryPillButton(
        label: 'Reset Password',
        onPressed: _canResetPassword ? _resetPassword : null,
        isLoading: _isSubmitting,
      ),
    ];
  }
}

class _LinkButton extends StatelessWidget {
  const _LinkButton({required this.label, required this.onPressed});

  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return TextButton(
      onPressed: onPressed,
      style: TextButton.styleFrom(foregroundColor: AppTheme.primaryBlue),
      child: Text(label),
    );
  }
}

/// Stands in for the user's mailbox while the fake backend is active, since
/// no real email is sent. Built whenever [ApiConfig.useFakeAuth] is true —
/// debug builds by default, or a release demo APK built with
/// `--dart-define=USE_FAKE_AUTH=true`. A build talking to the real backend
/// never shows it, so choir testers on real accounts never see a code.
class _DemoInbox extends ConsumerWidget {
  const _DemoInbox({required this.email});

  final String email;

  static const EdgeInsets _padding = EdgeInsets.fromLTRB(16, 12, 16, 12);
  static const double _radius = 16;
  static const double _iconGap = 12;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.watch(authApiProvider);
    final code = api is FakeAuthApi ? api.demoInboxCodeFor(email) : null;
    final textTheme = Theme.of(context).textTheme;

    return Container(
      padding: _padding,
      decoration: BoxDecoration(
        color: AppTheme.authFieldFill,
        borderRadius: BorderRadius.circular(_radius),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.inbox_outlined, color: AppTheme.authFieldIcon),
          const SizedBox(width: _iconGap),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Demo inbox (test backend only)',
                  style: textTheme.labelMedium?.copyWith(
                    color: AppTheme.authSubtitle,
                  ),
                ),
                Text(
                  code != null
                      ? 'Your reset code is $code'
                      : 'No email received for this address.',
                  style: textTheme.bodyMedium?.copyWith(
                    color: AppTheme.onboardingHeadingDark,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
