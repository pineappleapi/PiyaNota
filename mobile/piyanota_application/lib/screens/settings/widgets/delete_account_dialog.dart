import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../services/auth_api.dart';
import '../../../state/auth_providers.dart';
import '../../../theme/app_theme.dart';
import '../../auth/auth_messages.dart';
import '../../auth/widgets/auth_text_field.dart';
import '../settings_messages.dart';

/// How the dialog closed, for Settings to act on. Null means cancelled or
/// failed with the account still intact.
enum DeleteAccountResult { deleted, sessionExpired }

/// Contract J3. Two taps are needed: "Delete account" moves to a last
/// confirmation, and only "Yes, delete my account" sends the request. Only
/// [DeleteAccountResult.deleted] means the server purged the account; the
/// caller then wipes local data.
Future<DeleteAccountResult?> showDeleteAccountDialog(BuildContext context) =>
    showDialog<DeleteAccountResult>(
      context: context,
      // A tap outside must not drop a request in flight.
      barrierDismissible: false,
      builder: (_) => const _DeleteAccountDialog(),
    );

class _DeleteAccountDialog extends ConsumerStatefulWidget {
  const _DeleteAccountDialog();

  @override
  ConsumerState<_DeleteAccountDialog> createState() =>
      _DeleteAccountDialogState();
}

class _DeleteAccountDialogState extends ConsumerState<_DeleteAccountDialog> {
  static const double _gap = 14;

  final _password = TextEditingController();
  bool _confirming = false;
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _password.dispose();
    super.dispose();
  }

  void _askConfirmation() {
    if (_password.text.isEmpty) {
      setState(() => _error = SettingsMessages.deletePasswordRequired);
      return;
    }
    setState(() {
      _error = null;
      _confirming = true;
    });
  }

  Future<void> _delete() async {
    if (_submitting) return;
    setState(() {
      _submitting = true;
      _error = null;
    });
    String? error;
    var expired = false;
    var deleted = false;
    try {
      final token = await ref.read(sessionStorageProvider).readToken();
      if (token == null) throw const AuthSessionExpiredException();
      await ref
          .read(authApiProvider)
          .deleteAccount(token: token, password: _password.text);
      deleted = true;
    } on CurrentPasswordIncorrectException {
      error = SettingsMessages.wrongPassword;
    } on AuthSessionExpiredException {
      expired = true;
    } on AuthRateLimitedException catch (e) {
      error = SettingsMessages.rateLimited(e.retryAfterSeconds);
    } on AuthNetworkException {
      error = AuthMessages.network;
    } on AuthException {
      error = AuthMessages.serverError;
    } catch (e, stack) {
      // Never leave the button spinning on something unexpected.
      debugPrint('Delete account failed unexpectedly: $e\n$stack');
      error = AuthMessages.serverError;
    }
    if (!mounted) return;
    if (deleted || expired) {
      Navigator.of(context).pop(
        deleted
            ? DeleteAccountResult.deleted
            : DeleteAccountResult.sessionExpired,
      );
      return;
    }
    // Back to the password step: a wrong password is retyped, and after a
    // network failure the user decides again rather than the app retrying.
    setState(() {
      _submitting = false;
      _confirming = false;
      _error = error;
    });
  }

  @override
  Widget build(BuildContext context) {
    final error = _error;
    return AlertDialog(
      backgroundColor: AppTheme.settingsSurface,
      surfaceTintColor: Colors.transparent,
      title: Text(
        _confirming
            ? SettingsMessages.deleteConfirmTitle
            : SettingsMessages.deleteAccount,
      ),
      // Title and content scroll together, so 2x text on a small phone or
      // the keyboard never overflows.
      scrollable: true,
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            _confirming
                ? SettingsMessages.deleteConfirmBody
                : SettingsMessages.deleteAccountBody,
          ),
          if (!_confirming) ...[
            const SizedBox(height: _gap),
            AuthPasswordField(
              controller: _password,
              hintText: SettingsMessages.currentPassword,
              textInputAction: TextInputAction.done,
              autofillHints: const [AutofillHints.password],
              enabled: !_submitting,
              onFieldSubmitted: (_) => _askConfirmation(),
            ),
          ],
          if (error != null) ...[
            const SizedBox(height: _gap),
            Text(
              error,
              key: const ValueKey('delete-account-error'),
              style: const TextStyle(color: AppTheme.settingsLogOut),
            ),
          ],
        ],
      ),
      actions: [
        TextButton(
          onPressed: _submitting ? null : () => Navigator.of(context).pop(),
          style: TextButton.styleFrom(foregroundColor: AppTheme.settingsText),
          child: const Text(SettingsMessages.cancel),
        ),
        TextButton(
          key: const ValueKey('delete-account-confirm'),
          onPressed: _submitting
              ? null
              : (_confirming ? _delete : _askConfirmation),
          style: TextButton.styleFrom(
            foregroundColor: AppTheme.settingsLogOut,
            textStyle: const TextStyle(fontWeight: FontWeight.w700),
          ),
          child: Text(
            _submitting
                ? SettingsMessages.deletingAccount
                : _confirming
                ? SettingsMessages.deleteConfirmButton
                : SettingsMessages.deleteAccount,
          ),
        ),
      ],
    );
  }
}
