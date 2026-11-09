import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';
import '../../playback/sheet_parts.dart';

/// PIYA-212 AC9: a "?" beside a setting that opens a short explanation in
/// the same bottom sheet frame Playback uses, so it reads as part of the
/// app rather than a system dialog.
class HelpButton extends StatelessWidget {
  const HelpButton({
    super.key,
    required this.tooltip,
    required this.title,
    required this.body,
  });

  /// Also the screen-reader label.
  final String tooltip;
  final String title;
  final String body;

  static const double _iconSize = 22;
  static const double _bodyFontSize = 16;
  static const double _bodyLineHeight = 1.45;
  static const EdgeInsets _bodyPadding = EdgeInsets.fromLTRB(10, 4, 16, 8);

  void _open(BuildContext context) {
    showPlaybackSheet<void>(
      context,
      (sheetContext) => SheetFrame(
        title: title,
        children: [
          Padding(
            padding: _bodyPadding,
            child: Text(
              body,
              style: Theme.of(sheetContext).textTheme.bodyLarge?.copyWith(
                fontSize: _bodyFontSize,
                height: _bodyLineHeight,
                color: AppTheme.settingsText,
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // IconButton keeps the 48 dp target even though the glyph is small.
    return IconButton(
      tooltip: tooltip,
      onPressed: () => _open(context),
      color: AppTheme.settingsHelpIcon,
      iconSize: _iconSize,
      icon: const Icon(Icons.help_outline_rounded),
    );
  }
}
