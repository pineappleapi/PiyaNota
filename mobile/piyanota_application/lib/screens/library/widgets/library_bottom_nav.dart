import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';

/// The mockup's bottom bar: Library and Settings on a vertical blue→teal
/// gradient, with a raised white Capture button breaking its top edge.
///
/// The widget's own box includes the [protrusion] above the bar, left
/// transparent, so the Capture button's raised part is inside the hit-test
/// area (a child painted outside its parent's bounds can't be tapped).
/// Transparent areas aren't hit-testable, so the list scrolling behind that
/// strip stays tappable.
class LibraryBottomNav extends StatelessWidget {
  const LibraryBottomNav({
    super.key,
    required this.onLibrary,
    required this.onCapture,
    required this.onSettings,
  });

  final VoidCallback onLibrary;
  final VoidCallback onCapture;
  final VoidCallback onSettings;

  /// How far the Capture button rises above the bar (801 → 819 in the
  /// mockup).
  static const double protrusion = 18;

  /// Bar height above the bottom safe area / padding: bar top to the
  /// bottom of the labels in the mockup (819 → 893).
  static const double barHeight = 74;

  /// Space under the labels when the system reserves less (the mockup's
  /// 24 dp, which also matches a typical gesture-nav inset).
  static const double minBottomPadding = 24;

  // Item centres sit 112 dp either side of the Capture button (mockup:
  // 96 / 206 / 322 at 412 dp), shrinking proportionally on narrow phones.
  static const double _itemSpacing = 112;
  static const double _itemSpacingWidthFraction = 0.27;

  // A true circle (round-2 design polish; the mockup's 74x65 ellipse read as
  // a squashed button). 66 dp keeps the mockup's height, so the label under
  // it doesn't move.
  static const double _captureDiameter = 66;
  static const double _captureShadowBlur = 24;
  static const double _captureFrameSize = 53;
  static const double _captureNoteSize = 22;
  static const double _labelTop = 60;
  static const double _iconCenterFromBarTop = 34;
  static const double _libraryIconSize = 36;
  static const double _settingsIconSize = 30;
  static const double _labelFontSize = 13;
  // Selected-tab pill behind the icon, Material 3 NavigationBar-style but
  // sized for the larger 36 dp icons.
  static const double _indicatorWidth = 64;
  static const double _indicatorHeight = 40;

  /// Total height this widget occupies for a given bottom inset; the list
  /// above pads by this so its last card can scroll clear of the bar.
  static double heightFor(double bottomInset) =>
      protrusion + barHeight + _bottomPadding(bottomInset);

  static double _bottomPadding(double bottomInset) =>
      bottomInset > minBottomPadding ? bottomInset : minBottomPadding;

  @override
  Widget build(BuildContext context) {
    final bottomPadding = _bottomPadding(MediaQuery.paddingOf(context).bottom);
    final labelStyle = Theme.of(context).textTheme.labelLarge?.copyWith(
      fontSize: _labelFontSize,
      fontWeight: FontWeight.w400,
      color: Colors.white,
    );

    return LayoutBuilder(
      builder: (context, constraints) {
        final spacing = (constraints.maxWidth * _itemSpacingWidthFraction)
            .clamp(0.0, _itemSpacing);
        final center = constraints.maxWidth / 2;

        Widget item({required double centerX, required Widget child}) {
          return Positioned(
            top: protrusion,
            bottom: 0,
            left: centerX - spacing / 2,
            width: spacing,
            child: child,
          );
        }

        return SizedBox(
          height: protrusion + barHeight + bottomPadding,
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              const Positioned(
                top: protrusion,
                left: 0,
                right: 0,
                bottom: 0,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: AppTheme.libraryNavGradient,
                  ),
                ),
              ),
              item(
                centerX: center - spacing,
                child: _NavItem(
                  label: 'Library',
                  icon: CupertinoIcons.book_fill,
                  iconSize: _libraryIconSize,
                  labelStyle: labelStyle,
                  selected: true,
                  onTap: onLibrary,
                ),
              ),
              item(
                centerX: center + spacing,
                child: _NavItem(
                  label: 'Settings',
                  icon: Icons.settings,
                  iconSize: _settingsIconSize,
                  labelStyle: labelStyle,
                  onTap: onSettings,
                ),
              ),
              // Capture: the raised button plus its label under it.
              Positioned(
                top: 0,
                bottom: 0,
                left: center - spacing / 2,
                width: spacing,
                child: _CaptureButton(labelStyle: labelStyle, onTap: onCapture),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({
    required this.label,
    required this.icon,
    required this.iconSize,
    required this.labelStyle,
    required this.onTap,
    this.selected = false,
  });

  final String label;
  final IconData icon;
  final double iconSize;
  final TextStyle? labelStyle;
  final VoidCallback onTap;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      selected: selected,
      label: label,
      onTap: onTap,
      excludeSemantics: true,
      child: InkWell(
        onTap: onTap,
        splashFactory: NoSplash.splashFactory,
        // Darken-on-press SOP (frontend-piyanota.md "Interaction states"):
        // a darker shade of the gradient's dominant stop, the blue that
        // fills the icon/label band, not a black wash.
        highlightColor: AppTheme.darken(AppTheme.libraryNavTop),
        child: Stack(
          children: [
            if (selected)
              Positioned(
                top:
                    LibraryBottomNav._iconCenterFromBarTop -
                    LibraryBottomNav._indicatorHeight / 2,
                left: 0,
                right: 0,
                child: Center(
                  child: Container(
                    key: const ValueKey('library-nav-selected-indicator'),
                    width: LibraryBottomNav._indicatorWidth,
                    height: LibraryBottomNav._indicatorHeight,
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(
                        alpha: AppTheme.libraryNavIndicatorAlpha,
                      ),
                      borderRadius: BorderRadius.circular(
                        LibraryBottomNav._indicatorHeight / 2,
                      ),
                    ),
                  ),
                ),
              ),
            Positioned(
              top: LibraryBottomNav._iconCenterFromBarTop - iconSize / 2,
              left: 0,
              right: 0,
              child: Icon(icon, size: iconSize, color: Colors.white),
            ),
            Positioned(
              top: LibraryBottomNav._labelTop,
              left: 0,
              right: 0,
              child: _NavLabel(label, style: labelStyle),
            ),
          ],
        ),
      ),
    );
  }
}

class _CaptureButton extends StatelessWidget {
  const _CaptureButton({required this.labelStyle, required this.onTap});

  final TextStyle? labelStyle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    const shape = CircleBorder();

    return Semantics(
      button: true,
      label: 'Capture',
      onTap: onTap,
      excludeSemantics: true,
      child: GestureDetector(
        // The label under the button is part of the same target, like the
        // other two items.
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: Stack(
          clipBehavior: Clip.none,
          alignment: Alignment.topCenter,
          children: [
            Container(
              key: const ValueKey('library-capture-button'),
              width: LibraryBottomNav._captureDiameter,
              height: LibraryBottomNav._captureDiameter,
              decoration: const ShapeDecoration(
                shape: shape,
                shadows: [
                  BoxShadow(
                    color: AppTheme.libraryCaptureShadow,
                    blurRadius: LibraryBottomNav._captureShadowBlur,
                  ),
                ],
              ),
              child: Material(
                color: Colors.white,
                shape: shape,
                clipBehavior: Clip.antiAlias,
                child: InkWell(
                  onTap: onTap,
                  splashFactory: NoSplash.splashFactory,
                  highlightColor: AppTheme.darken(Colors.white),
                  child: const Stack(
                    alignment: Alignment.center,
                    children: [
                      Icon(
                        Icons.crop_free_rounded,
                        size: LibraryBottomNav._captureFrameSize,
                        color: AppTheme.libraryCardTitle,
                      ),
                      Icon(
                        Icons.music_note_rounded,
                        size: LibraryBottomNav._captureNoteSize,
                        color: AppTheme.libraryCardTitle,
                      ),
                    ],
                  ),
                ),
              ),
            ),
            Positioned(
              top: LibraryBottomNav.protrusion + LibraryBottomNav._labelTop,
              left: 0,
              right: 0,
              child: _NavLabel('Capture', style: labelStyle),
            ),
          ],
        ),
      ),
    );
  }
}

/// A nav label that is never cut off. On a narrow phone at large text the
/// item slot (~86 dp at 320 dp wide) is narrower than "Settings" at 2x, and
/// an ellipsized "Setti…" hides which tab it is. The label grows with the
/// system text scale up to [_maxTextScale], then shrinks to fit its slot.
class _NavLabel extends StatelessWidget {
  const _NavLabel(this.label, {required this.style});

  final String label;
  final TextStyle? style;

  static const double _maxTextScale = 1.5;

  @override
  Widget build(BuildContext context) {
    return MediaQuery.withClampedTextScaling(
      maxScaleFactor: _maxTextScale,
      child: FittedBox(
        fit: BoxFit.scaleDown,
        child: Text(
          label,
          textAlign: TextAlign.center,
          maxLines: 1,
          softWrap: false,
          style: style,
        ),
      ),
    );
  }
}
