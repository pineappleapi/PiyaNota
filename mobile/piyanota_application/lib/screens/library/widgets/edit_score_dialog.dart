import 'package:flutter/material.dart';

import '../../../models/score_details.dart';
import '../../../theme/app_theme.dart';
import '../../capture/capture_messages.dart';
import '../../capture/score_details_screen.dart' show CodePointLimitFormatter;
import '../library_messages.dart';

/// The title and arranger the user saved in [EditScoreDialog].
typedef EditedScoreDetails = ({String title, String? arranger});

/// PIYA-205-V2.4 AC2: only Title (required) and Arranger (optional),
/// pre-filled. Follows the capture details form (PIYA-206): the same labels,
/// the same 120 code point cap, and, as there, a blank title can't be
/// submitted (Save stays disabled). Pops [EditedScoreDetails] on Save and
/// null on Cancel (AC5).
class EditScoreDialog extends StatefulWidget {
  const EditScoreDialog({super.key, required this.title, this.arranger});

  final String title;
  final String? arranger;

  @override
  State<EditScoreDialog> createState() => _EditScoreDialogState();
}

class _EditScoreDialogState extends State<EditScoreDialog> {
  late final _title = TextEditingController(text: widget.title);
  late final _arranger = TextEditingController(text: widget.arranger ?? '');

  static const double _fieldGap = 12;
  static const List<CodePointLimitFormatter> _limit = [
    CodePointLimitFormatter(ScoreDetails.maxTextLength),
  ];

  @override
  void dispose() {
    _title.dispose();
    _arranger.dispose();
    super.dispose();
  }

  void _save() {
    final title = _title.text.trim();
    if (title.isEmpty) return;
    final arranger = _arranger.text.trim();
    Navigator.of(context)
        .pop((title: title, arranger: arranger.isEmpty ? null : arranger));
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
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
              textInputAction: TextInputAction.done,
              textCapitalization: TextCapitalization.words,
              inputFormatters: _limit,
              decoration: const InputDecoration(
                labelText: CaptureMessages.arrangerLabel,
              ),
              onSubmitted: (_) => _save(),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          style: TextButton.styleFrom(
            foregroundColor: AppTheme.libraryScoreSubtitle,
          ),
          child: const Text(LibraryMessages.editCancel),
        ),
        TextButton(
          onPressed: _title.text.trim().isEmpty ? null : _save,
          child: const Text(LibraryMessages.editSave),
        ),
      ],
    );
  }
}
