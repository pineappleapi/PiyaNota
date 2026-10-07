import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../routes/app_routes.dart';
import '../../services/auth_api.dart';
import '../../state/auth_providers.dart';
import '../../theme/app_theme.dart';
import '../../widgets/primary_pill_button.dart';
import 'auth_messages.dart';
import 'widgets/auth_error_banner.dart';
import 'widgets/auth_scaffold.dart';
import 'widgets/auth_switch_prompt.dart';
import 'widgets/auth_text_field.dart';

/// PIYA-202 — Login UI.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();

  bool _isSubmitting = false;
  String? _errorMessage;

  static const double _fieldGap = 16;
  static const double _sectionGap = 24;

  @override
  void initState() {
    super.initState();
    // Rebuild on every keystroke so the Log In button's enabled state
    // tracks AC1 ("disabled until both non-empty") live.
    _emailController.addListener(_onFieldsChanged);
    _passwordController.addListener(_onFieldsChanged);
  }

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  void _onFieldsChanged() => setState(() {});

  bool get _canSubmit =>
      !_isSubmitting &&
      _emailController.text.trim().isNotEmpty &&
      _passwordController.text.isNotEmpty;

  Future<void> _submit() async {
    if (!_canSubmit) return;
    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });

    String? error;
    try {
      final session = await ref.read(authApiProvider).login(
            email: _emailController.text.trim(),
            password: _passwordController.text,
          );
      await ref.read(sessionStorageProvider).save(session);
    } on InvalidCredentialsException {
      error = AuthMessages.incorrectCredentials;
    } on AuthNetworkException {
      error = AuthMessages.network;
    } on AuthValidationException catch (e) {
      error = e.serverMessage ?? AuthMessages.validationFallback;
    } on AuthException {
      error = AuthMessages.serverError;
    } on PlatformException {
      // Secure-storage write failed (e.g. Keystore unavailable). Treat the
      // login as failed rather than proceeding without a persisted token.
      error = AuthMessages.sessionSaveFailed;
    } catch (e, stack) {
      // Anything unmapped (misconfigured provider, unexpected storage error)
      // must still release the loading state, or the user is stuck behind a
      // spinner with disabled fields.
      debugPrint('Login failed unexpectedly: $e\n$stack');
      error = AuthMessages.serverError;
    }

    if (!mounted) return;
    if (error != null) {
      // Only the error and loading flag change — the typed email (and
      // password) stay in their controllers (AC2).
      setState(() {
        _isSubmitting = false;
        _errorMessage = error;
      });
      return;
    }
    Navigator.of(context).pushNamedAndRemoveUntil(
      AppRoutes.scoreLibrary,
      (_) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    final error = _errorMessage;

    return AuthScaffold(
      headline: 'Welcome back!',
      accentHeadline: 'Pick up where your\npart left off.',
      title: 'Log In',
      switchPrompt: AuthSwitchPrompt(
        prompt: "Don't have an account?",
        actionLabel: 'Sign Up',
        // Pushed, not replaced, so Android back on Sign-Up returns here
        // instead of exiting the app (Login is the root route).
        onPressed: _isSubmitting
            ? null
            : () => Navigator.of(context).pushNamed(AppRoutes.signUp),
      ),
      children: [
        if (error != null) ...[
          AuthErrorBanner(message: error),
          const SizedBox(height: _fieldGap),
        ],
        AutofillGroup(
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
              ),
              const SizedBox(height: _fieldGap),
              AuthPasswordField(
                controller: _passwordController,
                hintText: 'Password',
                textInputAction: TextInputAction.done,
                autofillHints: const [AutofillHints.password],
                enabled: !_isSubmitting,
                onFieldSubmitted: (_) => _submit(),
              ),
            ],
          ),
        ),
        Align(
          alignment: Alignment.centerRight,
          child: TextButton(
            onPressed: _isSubmitting
                ? null
                : () => Navigator.of(context).pushNamed(
                      AppRoutes.passwordReset,
                    ),
            style: TextButton.styleFrom(
              foregroundColor: AppTheme.primaryBlue,
            ),
            child: const Text('Forgot Password?'),
          ),
        ),
        const SizedBox(height: _sectionGap),
        PrimaryPillButton(
          label: 'Log In',
          onPressed: _canSubmit ? _submit : null,
          isLoading: _isSubmitting,
        ),
      ],
    );
  }
}
