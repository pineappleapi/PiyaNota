import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../routes/app_routes.dart';
import '../../services/auth_api.dart';
import '../../state/auth_providers.dart';
import '../../state/session_actions.dart';
import '../../theme/app_theme.dart';
import '../../widgets/primary_pill_button.dart';
import 'auth_messages.dart';
import 'password_reset_screen.dart';
import 'widgets/auth_error_banner.dart';
import 'widgets/auth_scaffold.dart';
import 'widgets/auth_switch_prompt.dart';
import 'widgets/auth_text_field.dart';

/// PIYA-202 — Login UI.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key, this.passwordReset});

  /// Set when Login is (re)built as the landing page of a completed reset
  /// that had no Login underneath to pop back to (PIYA-204 AC5). The usual
  /// path — reset pushed from "Forgot Password?" — delivers the same result
  /// via the route's pop value instead.
  final PasswordResetSucceeded? passwordReset;

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();

  bool _isSubmitting = false;
  String? _errorMessage;
  String? _noticeMessage;

  /// PIYA-202-V2.1: time left before the typed email may try again. Counted
  /// down by [_waitTimer] rather than re-read from the clock so the label
  /// and the button flip together.
  Duration _wait = Duration.zero;
  Timer? _waitTimer;
  String _waitEmail = '';

  static const Duration _waitTick = Duration(seconds: 1);

  static const double _fieldGap = 16;
  static const double _sectionGap = 24;

  @override
  void initState() {
    super.initState();
    final reset = widget.passwordReset;
    // Applied before the listeners attach so the prefill isn't a rebuild
    // request during initState.
    if (reset != null) _applyPasswordReset(reset);
    // Rebuild on every keystroke so the Log In button's enabled state
    // tracks AC1 ("disabled until both non-empty") live.
    _emailController.addListener(_onFieldsChanged);
    _passwordController.addListener(_onFieldsChanged);
    _syncWait();
  }

  @override
  void dispose() {
    _waitTimer?.cancel();
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  void _onFieldsChanged() {
    setState(() {});
    if (_emailController.text.trim().toLowerCase() != _waitEmail) _syncWait();
  }

  /// Loads the saved wait for the typed email, so another address is never
  /// blocked (AC4) and a reopened app keeps the wait.
  Future<void> _syncWait() async {
    final email = _emailController.text.trim().toLowerCase();
    _waitEmail = email;
    final left = email.isEmpty
        ? Duration.zero
        : await ref.read(loginThrottleProvider).remaining(email);
    // The user kept typing while we read; the newer call owns the state.
    if (!mounted || email != _waitEmail) return;
    _startWait(left);
  }

  void _startWait(Duration left) {
    _waitTimer?.cancel();
    // Round up so "29.99 s left" reads 0:30, not 0:29.
    final seconds = (left.inMilliseconds / 1000).ceil();
    setState(() => _wait = Duration(seconds: seconds));
    if (seconds <= 0) return;
    _waitTimer = Timer.periodic(_waitTick, (timer) {
      final next = _wait - _waitTick;
      setState(() => _wait = next.isNegative ? Duration.zero : next);
      if (_wait == Duration.zero) timer.cancel();
    });
  }

  bool get _canSubmit =>
      !_isSubmitting &&
      _wait == Duration.zero &&
      _emailController.text.trim().isNotEmpty &&
      _passwordController.text.isNotEmpty;

  /// PIYA-204 AC5: success confirmation, plus the reset email prefilled and
  /// any stale password cleared — the old one no longer works.
  void _applyPasswordReset(PasswordResetSucceeded reset) {
    _noticeMessage = AuthMessages.passwordResetSuccess;
    _errorMessage = null;
    if (reset.email.isNotEmpty) _emailController.text = reset.email;
    _passwordController.clear();
  }

  Future<void> _openPasswordReset() async {
    final result = await Navigator.of(context)
        .pushNamed(AppRoutes.passwordReset);
    if (!mounted || result is! PasswordResetSucceeded) return;
    setState(() => _applyPasswordReset(result));
  }

  Future<void> _submit() async {
    if (!_canSubmit) return;
    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
      _noticeMessage = null;
    });

    String? error;
    final email = _emailController.text.trim();
    final throttle = ref.read(loginThrottleProvider);
    Duration? newWait;
    try {
      final session = await ref
          .read(authApiProvider)
          .login(
            email: _emailController.text.trim(),
            password: _passwordController.text,
          );
      await throttle.reset(email);
      await startSession(ref, session);
    } on InvalidCredentialsException {
      error = AuthMessages.incorrectCredentials;
      await throttle.recordFailure(email);
      newWait = await throttle.remaining(email);
    } on AuthRateLimitedException catch (e) {
      // The server's wait replaces our own count (AC5).
      final seconds = e.retryAfterSeconds;
      if (seconds != null && seconds > 0) {
        await throttle.recordServerWait(email, Duration(seconds: seconds));
      } else {
        await throttle.recordFailure(email);
      }
      newWait = await throttle.remaining(email);
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
    if (newWait != null) _startWait(newWait);
    if (error != null || newWait != null) {
      // Only the error and loading flag change — the typed email (and
      // password) stay in their controllers (AC2).
      setState(() {
        _isSubmitting = false;
        _errorMessage = error;
      });
      return;
    }
    Navigator.of(context)
        .pushNamedAndRemoveUntil(AppRoutes.scoreLibrary, (_) => false);
  }

  @override
  Widget build(BuildContext context) {
    final error = _errorMessage;
    final notice = _noticeMessage;

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
        if (notice != null) ...[
          AuthNoticeBanner(message: notice),
          const SizedBox(height: _fieldGap),
        ],
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
            onPressed: _isSubmitting ? null : _openPasswordReset,
            style: TextButton.styleFrom(foregroundColor: AppTheme.primaryBlue),
            child: const Text('Forgot Password?'),
          ),
        ),
        const SizedBox(height: _sectionGap),
        if (_wait > Duration.zero) ...[
          Text(
            AuthMessages.tryAgainIn(_wait),
            textAlign: TextAlign.center,
            style: const TextStyle(color: AppTheme.primaryBlue),
          ),
          const SizedBox(height: _fieldGap),
        ],
        PrimaryPillButton(
          label: 'Log In',
          onPressed: _canSubmit ? _submit : null,
          isLoading: _isSubmitting,
        ),
      ],
    );
  }
}
