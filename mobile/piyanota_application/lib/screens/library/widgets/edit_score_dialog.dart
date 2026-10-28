import 'package:flutter/material.dart';

import '../../../models/score_details.dart';
import '../../../services/score_library_api.dart';
import '../../../theme/app_theme.dart';
import '../../capture/capture_messages.dart';
import '../../capture/score_details_screen.dart' show CodePointLimitFormatter;
import '../library_messages.dart';

/// The title and arranger the user saved in [EditScoreDialog].
typedef EditedScoreDetails = ({String title, String? arranger});

/// PIYA-205-V2.4 AC2: only Title (required) and Arranger (optional),
/// pre-filled. Follows the capture details form (PIYA-206): the same labels,
/// the same 120 code point cap, and, as there, a blank title can't be
/// submitted (Save stays disabled).
///
/// Save runs [onSave] with the dialog still open: both buttons are disabled
/// behind a spinner, and a thrown [ScoreLibraryNetworkException] or other
/// failure shows an inline error with the typed text kept, so the user can
/// retry. The dialog closes only when [onSave] returns (AC4) or on Cancel
/// (AC5). [onSave] handles the outcomes that end the edit instead of failing
/// it (404, expired session) and returns normally for them.
class EditScoreDialog extends StatefulWidget {
  const EditScoreDialog({
    super.key,
    required this.title,
    required this.onSave,
    this.arranger,
  });

  final String title;
  final String? arranger;
  final Future<void> Function(EditedScoreDetails details) onSave;

  @override
  State<EditScoreDialog> createState() => _EditScoreDialogState();
}

class _EditScoreDialogState extends State<EditScoreDialog> {
  late final _title = TextEditingController(text: widget.title);
  late final _arranger = TextEditingController(text: widget.arranger ?? '');
  bool _saving = false;
  String? _error;

  static const double _fieldGap = 12;
  static const double _spinnerSize = 16;
  static const double _spinnerStroke = 2;
  static const List<CodePointLimitFormatter> _limit = [
    CodePointLimitFormatter(ScoreDetails.maxTextLength),
  ];

  @override
  void dispose() {
    _title.dispose();
    _arranger.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final title = _title.text.trim();
    if (title.isEmpty || _saving) return;
    final arranger = _arranger.text.trim();
    // Nothing changed: no request, no "saved" message.
    if (title == widget.title.trim() &&
        arranger == (widget.arranger ?? '').trim()) {
      Navigator.of(context).pop();
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.onSave((
        title: title,
        arranger: arranger.isEmpty ? null : arranger,
      ));
      if (mounted) Navigator.of(context).pop();
    } on ScoreLibraryNetworkException {
      _fail(LibraryMessages.editNetworkError);
    } on Object {
      _fail(LibraryMessages.editServerError);
    }
  }

  void _fail(String message) {
    if (!mounted) return;
    setState(() {
      _saving = false;
      _error = message;
    });
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: !_saving,
      child: AlertDialog(
        backgroundColor: Colors.white,
        title: const Text(LibraryMessages.editDialogTitle),
        // Scrolls so 2x text on a 320 dp phone with the keyboard up can't
        // overflow.
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                key: const Key('edit-title'),
                controller: _title,
                autofocus: true,
                enabled: !_saving,
                textInputAction: TextInputAction.next,
                textCapitalization: TextCapitalization.words,
                inputFormatters: _limit,
                decoration: const InputDecoration(
                  labelText: CaptureMessages.titleLabel,
                ),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: _fieldGap),
              TextField(
                key: const Key('edit-arranger'),
                controller: _arranger,
                enabled: !_saving,
                textInputAction: TextInputAction.done,
                textCapitalization: TextCapitalization.words,
                inputFormatters: _limit,
                decoration: const InputDecoration(
                  labelText: CaptureMessages.arrangerLabel,
                ),
                onSubmitted: (_) => _save(),
              ),
              if (_error != null) ...[
                const SizedBox(height: _fieldGap),
                Text(_error!, style: const TextStyle(color: AppTheme.errorRed)),
              ],
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: _saving ? null : () => Navigator.of(context).pop(),
            style: TextButton.styleFrom(
              foregroundColor: AppTheme.libraryScoreSubtitle,
            ),
            child: const Text(LibraryMessages.editCancel),
          ),
          TextButton(
            onPressed: _saving || _title.text.trim().isEmpty ? null : _save,
            child: _saving
                ? const SizedBox.square(
                    key: Key('edit-saving'),
                    dimension: _spinnerSize,
                    child: CircularProgressIndicator(
                      strokeWidth: _spinnerStroke,
                      semanticsLabel: LibraryMessages.editSaving,
                    ),
                  )
                : const Text(LibraryMessages.editSave),
          ),
        ],
      ),
    );
  }
}
