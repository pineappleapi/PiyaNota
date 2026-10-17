import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../services/auth_api.dart';
import '../../../services/auth_validators.dart';
import '../../../state/auth_providers.dart';
import '../../../widgets/primary_pill_button.dart';
import '../../auth/auth_messages.dart';
import '../../auth/widgets/auth_error_banner.dart';
import '../../auth/widgets/auth_text_field.dart';
import '../../playback/sheet_parts.dart';
import '../settings_messages.dart';

/// How the sheet closed, for Settings to act on.
enum ChangePasswordResult { changed, logInAgain }

/// Opens the PIYA-212 AC6 form. Completes with null when dismissed.
Future<ChangePasswordResult?> showChangePasswordSheet(BuildContext context) =>
    // Drag is off so a swipe can't drop a request in flight; the X is
    // disabled for the same reason while it runs.
    showPlaybackSheet<ChangePasswordResult>(
      context,
      (_) => const ChangePasswordSheet(),
      enableDrag: false,
    );

/// Current, new and confirm, with the Sign-Up strength rule (PIYA-203) on
/// the new password. PIYA-322's verdicts land where the user can act on
/// them: a 403 under the current-password field (AC6), a `weak_password`
/// 400 under the new one in the app's own Sign-Up wording, a 429 as a
/// banner saying how long to wait. A dead session (any 401) offers Log in
/// instead, since retyping can't fix it.
class ChangePasswordSheet extends ConsumerStatefulWidget {
  const ChangePasswordSheet({super.key});

  @override
  ConsumerState<ChangePasswordSheet> createState() =>
      _ChangePasswordSheetState();
}

class _ChangePasswordSheetState extends ConsumerState<ChangePasswordSheet> {
  static const double _fieldGap = 14;
  static const double _sectionGap = 20;
  static const EdgeInsets _bodyPadding = EdgeInsets.fromLTRB(10, 8, 8, 8);

  final _formKey = GlobalKey<FormState>();
  final _currentController = TextEditingController();
  final _newController = TextEditingController();
  final _confirmController = TextEditingController();

  bool _submitting = false;
  bool _currentRejected = false;
  bool _newRejected = false;
  String? _error;
  bool _sessionExpired = false;

  @override
  void initState() {
    super.initState();
    // A server verdict is about the text it was given; editing that field
    // withdraws it.
    _currentController.addListener(() {
      if (_currentRejected) {
        setState(() => _currentRejected = false);
        _formKey.currentState?.validate();
      }
    });
    _newController.addListener(() {
      if (_newRejected) {
        setState(() => _newRejected = false);
        _formKey.currentState?.validate();
      }
    });
  }

  @override
  void dispose() {
    _currentController.dispose();
    _newController.dispose();
    _confirmController.dispose();
    super.dispose();
  }

  String? _validateCurrent(String? value) {
    if ((value ?? '').isEmpty) return SettingsMessages.currentPasswordRequired;
    if (_currentRejected) return SettingsMessages.currentPasswordIncorrect;
    return null;
  }

  // A server `weak_password` gets the same wording as the client check:
  // the server's validator is shared with Sign-Up (PIYA-322 AC4), so the
  // rule is the same even when this client's copy of it has drifted.
  // Reads the controller, not the field's value: the listener above runs
  // before the field's own and would otherwise validate the old text.
  String? _validateNew(String? _) =>
      !_newRejected && AuthValidators.meetsPasswordPolicy(_newController.text)
      ? null
      : AuthMessages.passwordTooWeak;

  String? _validateConfirm(String? value) =>
      value == _newController.text ? null : AuthMessages.passwordsDoNotMatch;

  Future<void> _submit() async {
    if (_submitting) return;
    setState(() {
      _currentRejected = false;
      _newRejected = false;
      _error = null;
      _sessionExpired = false;
    });
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _submitting = true);

    String? error;
    var expired = false;
    var rejected = false;
    var weak = false;
    try {
      final token = await ref.read(sessionStorageProvider).readToken();
      if (token == null) throw const AuthSessionExpiredException();
      await ref
          .read(authApiProvider)
          .changePassword(
            token: token,
            currentPassword: _currentController.text,
            newPassword: _newController.text,
          );
    } on CurrentPasswordIncorrectException {
      rejected = true;
    } on AuthSessionExpiredException {
      expired = true;
      error = SettingsMessages.sessionExpired;
    } on AuthRateLimitedException catch (e) {
      error = SettingsMessages.rateLimited(e.retryAfterSeconds);
    } on AuthNetworkException {
      error = AuthMessages.network;
    } on AuthValidationException catch (e) {
      // `message` is log text (PIYA-101 AC9), never shown. Any other 400
      // (e.g. `missing_field`) means this client sent a malformed request.
      if (e.code == weakPasswordCode) {
        weak = true;
      } else {
        debugPrint('Change password rejected: ${e.code} ${e.field}');
        error = AuthMessages.validationFallback;
      }
    } on AuthException {
      error = AuthMessages.serverError;
    } catch (e, stack) {
      // Never leave the button spinning on something unexpected.
      debugPrint('Change password failed unexpectedly: $e\n$stack');
      error = AuthMessages.serverError;
    }

    if (!mounted) return;
    if (error == null && !rejected && !weak) {
      Navigator.of(context).pop(ChangePasswordResult.changed);
      return;
    }
    setState(() {
      _submitting = false;
      _currentRejected = rejected;
      _newRejected = weak;
      _error = error;
      _sessionExpired = expired;
    });
    if (rejected || weak) _formKey.currentState?.validate();
  }

  @override
  Widget build(BuildContext context) {
    final error = _error;
    // The sheet scrolls; lifting it by the keyboard keeps the focused
    // field and the button above it.
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SheetFrame(
        title: SettingsMessages.changePassword,
        canClose: !_submitting,
        children: [
          Padding(
            padding: _bodyPadding,
            child: Form(
              key: _formKey,
              child: AutofillGroup(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    AuthPasswordField(
                      controller: _currentController,
                      hintText: SettingsMessages.currentPassword,
                      textInputAction: TextInputAction.next,
                      autofillHints: const [AutofillHints.password],
                      enabled: !_submitting,
                      validator: _validateCurrent,
                    ),
                    const SizedBox(height: _fieldGap),
                    AuthPasswordField(
                      controller: _newController,
                      hintText: SettingsMessages.newPassword,
                      textInputAction: TextInputAction.next,
                      autofillHints: const [AutofillHints.newPassword],
                      enabled: !_submitting,
                      validator: _validateNew,
                      helperText: AuthValidators.passwordPolicyDescription,
                    ),
                    const SizedBox(height: _fieldGap),
                    AuthPasswordField(
                      controller: _confirmController,
                      hintText: SettingsMessages.confirmNewPassword,
                      textInputAction: TextInputAction.done,
                      autofillHints: const [AutofillHints.newPassword],
                      enabled: !_submitting,
                      validator: _validateConfirm,
                      onFieldSubmitted: (_) => _submit(),
                    ),
                    if (error != null) ...[
                      const SizedBox(height: _sectionGap),
                      AuthErrorBanner(
                        message: error,
                        actionLabel: _sessionExpired
                            ? SettingsMessages.logIn
                            : null,
                        onAction: _sessionExpired
                            ? () =>
                                  Navigator.of(context)
                                      .pop(ChangePasswordResult.logInAgain)
                            : null,
                      ),
                    ],
                    const SizedBox(height: _sectionGap),
                    PrimaryPillButton(
                      label: SettingsMessages.changePassword,
                      loadingLabel: SettingsMessages.changingPassword,
                      isLoading: _submitting,
                      onPressed: _submit,
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
