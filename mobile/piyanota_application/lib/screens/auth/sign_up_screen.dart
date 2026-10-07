import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../routes/app_routes.dart';
import '../../services/auth_api.dart';
import '../../services/auth_validators.dart';
import '../../state/auth_providers.dart';
import '../../widgets/primary_pill_button.dart';
import 'auth_messages.dart';
import 'widgets/auth_error_banner.dart';
import 'widgets/auth_scaffold.dart';
import 'widgets/auth_switch_prompt.dart';
import 'widgets/auth_text_field.dart';

/// PIYA-203 — Sign-Up UI.
class SignUpScreen extends ConsumerStatefulWidget {
  const SignUpScreen({super.key});

  @override
  ConsumerState<SignUpScreen> createState() => _SignUpScreenState();
}

class _SignUpScreenState extends ConsumerState<SignUpScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmController = TextEditingController();

  bool _isSubmitting = false;
  // Field errors stay hidden until the first Create Account tap, then track
  // every keystroke — flagging "invalid email" mid-typing is just noise.
  bool _submitAttempted = false;
  String? _errorMessage;
  bool _showLoginAction = false;

  static const double _fieldGap = 16;
  static const double _sectionGap = 24;

  @override
  void initState() {
    super.initState();
    for (final controller in _controllers) {
      controller.addListener(_onFieldsChanged);
    }
  }

  @override
  void dispose() {
    for (final controller in _controllers) {
      controller.dispose();
    }
    super.dispose();
  }

  List<TextEditingController> get _controllers =>
      [_emailController, _passwordController, _confirmController];

  void _onFieldsChanged() => setState(() {});

  /// AC1: enabled only once all three fields are filled. Format/strength/
  /// match problems are reported on tap (AC2–4), not by disabling, so the
  /// user always gets told *why* they can't proceed.
  bool get _canSubmit =>
      !_isSubmitting &&
      _emailController.text.trim().isNotEmpty &&
      _passwordController.text.isNotEmpty &&
      _confirmController.text.isNotEmpty;

  String? _validateEmail(String? value) {
    final email = value?.trim() ?? '';
    if (email.isEmpty) return AuthMessages.emailRequired;
    if (!AuthValidators.isValidEmail(email)) return AuthMessages.emailInvalid;
    return null;
  }

  String? _validatePassword(String? value) {
    return AuthValidators.meetsPasswordPolicy(value ?? '')
        ? null
        : AuthMessages.passwordTooWeak;
  }

  String? _validateConfirmation(String? value) {
    return value == _passwordController.text
        ? null
        : AuthMessages.passwordsDoNotMatch;
  }

  Future<void> _submit() async {
    if (!_canSubmit) return;
    setState(() => _submitAttempted = true);
    final form = _formKey.currentState;
    // Client-side checks gate the request entirely (AC2–4: "before
    // submission").
    if (form == null || !form.validate()) return;

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
      _showLoginAction = false;
    });

    String? error;
    var offerLogin = false;
    try {
      final session = await ref.read(authApiProvider).signUp(
            email: _emailController.text.trim(),
            password: _passwordController.text,
            passwordConfirmation: _confirmController.text,
          );
      // AC6: the sign-up response already carries a session token, so the
      // user is logged in here with no separate Login round trip.
      await ref.read(sessionStorageProvider).save(session);
    } on EmailAlreadyRegisteredException {
      error = AuthMessages.emailAlreadyRegistered;
      offerLogin = true;
    } on AuthNetworkException {
      error = AuthMessages.network;
    } on AuthValidationException catch (e) {
      error = e.serverMessage ?? AuthMessages.validationFallback;
    } on AuthException {
      error = AuthMessages.serverError;
    } on PlatformException {
      error = AuthMessages.sessionSaveFailed;
    } catch (e, stack) {
      // See LoginScreen._submit: never leave the button stuck loading.
      debugPrint('Sign-up failed unexpectedly: $e\n$stack');
      error = AuthMessages.serverError;
    }

    if (!mounted) return;
    if (error != null) {
      setState(() {
        _isSubmitting = false;
        _errorMessage = error;
        _showLoginAction = offerLogin;
      });
      return;
    }
    Navigator.of(context).pushNamedAndRemoveUntil(
      AppRoutes.scoreLibrary,
      (_) => false,
    );
  }

  /// Sign-Up is either pushed over Login, or the root route when reached
  /// from onboarding's Get Started (PIYA-201 AC6). Pop back to the existing
  /// Login in the first case rather than stacking a second one.
  void _goToLogin() {
    final navigator = Navigator.of(context);
    if (navigator.canPop()) {
      navigator.pop();
    } else {
      navigator.pushReplacementNamed(AppRoutes.login);
    }
  }

  @override
  Widget build(BuildContext context) {
    final error = _errorMessage;

    // As the root route, system back would otherwise close the app — send
    // the user to Login instead, which is where they'd expect to land.
    return PopScope(
      canPop: Navigator.of(context).canPop(),
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && !_isSubmitting) _goToLogin();
      },
      child: _buildScaffold(error),
    );
  }

  Widget _buildScaffold(String? error) {
    return AuthScaffold(
      headline: 'Create your account',
      accentHeadline: 'and start rehearsing\nyour part.',
      title: 'Sign Up',
      switchPrompt: AuthSwitchPrompt(
        prompt: 'Already have an account?',
        actionLabel: 'Log In',
        onPressed: _isSubmitting ? null : _goToLogin,
      ),
      children: [
        if (error != null) ...[
          AuthErrorBanner(
            message: error,
            actionLabel: _showLoginAction ? 'Log in instead' : null,
            onAction: _showLoginAction ? _goToLogin : null,
          ),
          const SizedBox(height: _fieldGap),
        ],
        Form(
          key: _formKey,
          autovalidateMode: _submitAttempted
              ? AutovalidateMode.always
              : AutovalidateMode.disabled,
          child: AutofillGroup(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                AuthTextField(
                  controller: _emailController,
                  hintText: 'Enter your email address',
                  icon: Icons.mail_outline_rounded,
                  keyboardType: TextInputType.emailAddress,
                  textInputAction: TextInputAction.next,
                  autofillHints: const [AutofillHints.email],
                  enabled: !_isSubmitting,
                  validator: _validateEmail,
                ),
                const SizedBox(height: _fieldGap),
                AuthPasswordField(
                  controller: _passwordController,
                  hintText: 'Password',
                  textInputAction: TextInputAction.next,
                  autofillHints: const [AutofillHints.newPassword],
                  enabled: !_isSubmitting,
                  validator: _validatePassword,
                  helperText: AuthValidators.passwordPolicyDescription,
                ),
                const SizedBox(height: _fieldGap),
                AuthPasswordField(
                  controller: _confirmController,
                  hintText: 'Confirm password',
                  textInputAction: TextInputAction.done,
                  autofillHints: const [AutofillHints.newPassword],
                  enabled: !_isSubmitting,
                  validator: _validateConfirmation,
                  onFieldSubmitted: (_) => _submit(),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: _sectionGap),
        PrimaryPillButton(
          label: 'Create Account',
          onPressed: _canSubmit ? _submit : null,
          isLoading: _isSubmitting,
        ),
      ],
    );
  }
}
