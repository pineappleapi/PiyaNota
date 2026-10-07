import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../config/api_config.dart';
import '../../routes/app_routes.dart';
import '../../services/auth_api.dart';
import '../../services/auth_validators.dart';
import '../../services/fake_auth_api.dart';
import '../../state/auth_providers.dart';
import '../../theme/app_theme.dart';
import '../../widgets/primary_pill_button.dart';
import 'auth_messages.dart';
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
/// PIYA-303/304 have no "verify code" endpoint — the code is the confirm
/// call's `resetToken` — so the code step only checks its shape locally,
/// and a bad code surfaces as a 410 after the new password is submitted.
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

  /// The email the current code was requested for — fixed at request time
  /// so editing the (hidden) email field can't change what Login receives.
  String _requestedEmail = '';

  /// Last-seen text per controller. Listeners also fire on cursor moves,
  /// so only a real text change may clear a stale error banner.
  late final Map<TextEditingController, String> _lastTexts = {
    for (final c in _controllers) c: c.text,
  };

  static const double _fieldGap = 16;
  static const double _sectionGap = 24;

  List<TextEditingController> get _controllers => [
    _emailController,
    _codeController,
    _passwordController,
    _confirmController,
  ];

  @override
  void initState() {
    super.initState();
    for (final controller in _controllers) {
      controller.addListener(() => _onFieldChanged(controller));
    }
  }

  @override
  void dispose() {
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
      if (textChanged && !_isSubmitting) _errorMessage = null;
    });
  }

  String get _code => _codeController.text.trim();

  // AC1: Submit disabled until non-empty *and* well-formatted.
  bool get _canRequestCode =>
      !_isSubmitting && AuthValidators.isValidEmail(_emailController.text);

  bool get _canContinueWithCode =>
      !_isSubmitting && AuthValidators.isWellFormedResetCode(_code);

  bool get _canResetPassword =>
      !_isSubmitting &&
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
    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
      _noticeMessage = null;
    });

    String? error;
    try {
      await ref.read(authApiProvider).requestPasswordReset(email: email);
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
    if (error == null) _codeController.clear();
    setState(() {
      _isSubmitting = false;
      if (error != null) {
        _errorMessage = error;
        return;
      }
      // AC2/AC3: identical outcome for registered and unregistered emails —
      // nothing here may depend on whether a code was really sent.
      _requestedEmail = email;
      _noticeMessage = AuthMessages.resetCodeSent;
      _step = _ResetStep.code;
    });
  }

  void _continueWithCode() {
    if (!_canContinueWithCode) return;
    setState(() {
      _errorMessage = null;
      _noticeMessage = null;
      _step = _ResetStep.newPassword;
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
    try {
      await ref
          .read(authApiProvider)
          .confirmPasswordReset(
            resetToken: _code,
            newPassword: _passwordController.text,
            newPasswordConfirmation: _confirmController.text,
          );
    } on ResetCodeInvalidException {
      error = AuthMessages.resetCodeInvalid;
      codeRejected = true;
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
    if (error == null) {
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
      if (codeRejected) _step = _ResetStep.code;
      _errorMessage = error;
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
            label: 'Resend code',
            onPressed: _isSubmitting ? null : _requestCode,
          ),
        ],
      ),
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
/// no real email is sent. Only ever built when [ApiConfig.useFakeAuth] is
/// true (debug builds by default), so release builds — and therefore choir
/// testers — never see a reset code on screen.
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
                  'Demo inbox (debug build only)',
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
