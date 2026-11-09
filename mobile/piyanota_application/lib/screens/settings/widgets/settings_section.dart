import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';

/// One Settings group: a sentence-case name on the page background, then
/// a white rounded card holding its rows, split by hairline dividers.
class SettingsSection extends StatelessWidget {
  const SettingsSection({
    super.key,
    required this.title,
    required this.children,
  });

  final String title;
  final List<Widget> children;

  static const double radius = 16;
  static const double _titleFontSize = 14;
  static const double _titleBottomGap = 8;
  static const double _titleInset = 4;
  static const double _dividerInset = 16;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.only(
            left: _titleInset,
            bottom: _titleBottomGap,
          ),
          child: Semantics(
            header: true,
            child: Text(
              title,
              style: Theme.of(context).textTheme.titleSmall?.copyWith(
                fontSize: _titleFontSize,
                fontWeight: FontWeight.w600,
                color: AppTheme.settingsGroupLabel,
              ),
            ),
          ),
        ),
        Material(
          color: AppTheme.settingsSurface,
          borderRadius: BorderRadius.circular(radius),
          // Clips row ink to the rounded corners.
          clipBehavior: Clip.antiAlias,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              for (var i = 0; i < children.length; i++) ...[
                if (i > 0)
                  const Divider(
                    height: 1,
                    thickness: 1,
                    indent: _dividerInset,
                    endIndent: _dividerInset,
                    color: AppTheme.settingsDivider,
                  ),
                children[i],
              ],
            ],
          ),
        ),
      ],
    );
  }
}

/// Text styles shared by the rows, so every group reads the same.
class SettingsText {
  SettingsText._();

  static const double _labelFontSize = 16;
  static const double _captionFontSize = 13;

  static TextStyle? label(BuildContext context) =>
      Theme.of(context).textTheme.bodyLarge?.copyWith(
        fontSize: _labelFontSize,
        fontWeight: FontWeight.w600,
        color: AppTheme.settingsText,
      );

  static TextStyle? value(BuildContext context) =>
      Theme.of(context).textTheme.bodyLarge
          ?.copyWith(fontSize: _labelFontSize, color: AppTheme.settingsText);

  static TextStyle? caption(BuildContext context) => Theme.of(context)
      .textTheme
      .bodySmall
      ?.copyWith(fontSize: _captionFontSize, color: AppTheme.settingsSubtle);
}

/// Inner padding of every row, so text lines up across groups.
const EdgeInsets kSettingsRowPadding = EdgeInsets.symmetric(
  horizontal: 16,
  vertical: 14,
);
