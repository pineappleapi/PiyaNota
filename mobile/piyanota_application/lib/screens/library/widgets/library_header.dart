import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';
import '../../scan_status/scan_bell.dart';
import '../library_messages.dart';

/// Gradient top section of the Score Library: "My Scores" and a status
/// subtitle on the left, the bell in the top-right corner, a large faded
/// logo mark behind everything on the left, then the outlined search field.
///
/// Dimensions are read off the 412 dp-wide mockup (1 px = 1 dp there),
/// except the logo (PIYA-205-V2.1), which is measured off the v2 reference.
class LibraryHeader extends StatelessWidget {
  const LibraryHeader({
    super.key,
    required this.subtitle,
    this.title = LibraryMessages.title,
    this.searchController,
    this.onSearchChanged,
    required this.horizontalPadding,
  });

  final String title;
  final String subtitle;
  // Settings passes neither: no search field, same header otherwise.
  final TextEditingController? searchController;
  final ValueChanged<String>? onSearchChanged;
  final double horizontalPadding;

  static const String _logoAsset = 'assets/branding/Piyanota_App_Logo.png';
  // The PNG's mark spans x 528–1450, y 398–1631 of its 2000 px canvas
  // (measured from the alpha channel), so the canvas is drawn larger than
  // the box and overflows it, leaving the box the size of the mark itself.
  // That lets the mark's top and right edges line up with the safe-area gap
  // and the search field's right edge exactly.
  static const double _logoMarkHeight = 72;
  static const double logoMarkWidth = 54;
  // 72 / 0.6165 (mark height fraction). The mark is centred on the canvas
  // to within 1 dp, so OverflowBox's default centring needs no offset.
  static const double _logoCanvasSize = 117;

  /// Breathing room between the status bar (safe area) and the header
  /// content, so neither the logo nor the title touches the top edge.
  static const double topGap = 12;
  static const double titleToLogoGap = 12;

  // Backdrop logo (PIYA-205-V2.1), measured on PIYA205_HomePage_Version2.png
  // (412 px wide = 412 dp, so 1 px = 1 dp; header block 246 dp tall):
  // mark's right edge x=191, top y=27, left edge at x=0 (cropped by the
  // screen edge); its bottom runs past the header and is clipped. Size is
  // from the P's counter (hole) vs the asset's: 0.21 dp per asset px.
  static const double _backdropLogoWidth = 191;
  static const double _backdropLogoHeight = 256;
  // Measured from the header top including the reference's status bar, so it
  // does not follow the safe-area inset (a backdrop); needs a phone check.
  static const double _backdropLogoTop = 27;

  // Bell (PIYA-205-V2.1 AC4), reference ink bbox x 352..383, y 61..94: ~32 dp
  // wide, right inset 28-29 dp. The Material bell's ink is 16/24 of its icon
  // box wide and stops 4/24 short of the box's right edge, so a 44 dp icon
  // gives ~29 dp of ink; the 48 dp hit box is centred on it (2 dp each side).
  static const double _bellIconSize = 44;
  static const double _bellInkRightInset = 29;
  static const double _bellRight =
      _bellInkRightInset -
      _bellIconSize * 4 / 24 -
      (ScanBell.size - _bellIconSize) / 2;
  // 256 / 0.6165 (mark height fraction of the 2000 px canvas).
  static const double _backdropLogoCanvas = 415;

  /// Title top below the safe area, as in round 1 (61f5583): its 2 dp top
  /// gap + the 49 dp centred mark + a 10 dp gap. The mark has since moved
  /// to the corner, but the user asked to keep the text where it was
  /// (2026-10-08), so the offset stays even though the space is now empty.
  static const double titleTop = 61;
  static const double _subtitleToSearchGap = 10;
  static const double bottomGap = 16;
  static const double titleFontSize = 34;
  static const double titleLineHeight = 1.2;
  static const double subtitleLineHeight = 1.25;

  /// The 34 sp heading and its subtitle stop growing past 1.5x. Android 14+
  /// already scales large text nonlinearly (a 34 sp title at 200% renders
  /// near 1.5x), and on a 320 dp phone at a linear 2x the heading alone
  /// filled the screen and pushed the list out of view (NFR-10). The search
  /// field and the cards keep the full system scale.
  static const double headingMaxTextScale = 1.5;

  /// Above this scale the decorative mark is dropped so the heading gets
  /// the full width instead of wrapping word-by-word beside it.
  static const double logoMaxTextScale = 1.3;
  static const double subtitleFontSize = 15;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final textScale =
        MediaQuery.textScalerOf(context).scale(subtitleFontSize) /
        subtitleFontSize;
    final showLogo = textScale <= logoMaxTextScale;

    return DecoratedBox(
      decoration: const BoxDecoration(gradient: AppTheme.libraryHeaderGradient),
      // The backdrop logo is laid out on the header itself (not inside the
      // padded content) so it can touch the left screen edge, and is clipped
      // at the header's bottom as in the reference.
      child: Stack(
        children: [
          if (showLogo)
            const Positioned(
              left: 0,
              top: _backdropLogoTop,
              child: _BackdropLogo(),
            ),
          SafeArea(
            bottom: false,
            child: Padding(
              padding: EdgeInsets.fromLTRB(
                horizontalPadding,
                topGap,
                horizontalPadding,
                bottomGap,
              ),
              child: Stack(
                children: [
                  // PIYA-218 AC5 / PIYA-205-V2.1 AC4: far top-right corner, in
                  // the empty band above the title (in the title's row when
                  // the logo band is dropped at large text).
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      // Round-1 position at normal sizes. At large text the
                      // mark is hidden and its band is dropped too, so on a
                      // 320 dp phone at 2x the results stay in view (NFR-10).
                      SizedBox(height: showLogo ? titleTop - topGap : 0),
                      MediaQuery.withClampedTextScaling(
                        maxScaleFactor: headingMaxTextScale,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Padding(
                              // The bell is above the title when the band is
                              // kept; otherwise it shares the title's row.
                              padding: EdgeInsets.only(
                                right: showLogo
                                    ? 0
                                    : ScanBell.size + titleToLogoGap,
                              ),
                              child: Semantics(
                                header: true,
                                child: Text(
                                  title,
                                  style: textTheme.headlineLarge?.copyWith(
                                    fontSize: titleFontSize,
                                    fontWeight: FontWeight.w700,
                                    height: titleLineHeight,
                                    color: Colors.white,
                                  ),
                                ),
                              ),
                            ),
                            Text(
                              subtitle,
                              style: textTheme.bodyLarge?.copyWith(
                                fontSize: subtitleFontSize,
                                height: subtitleLineHeight,
                                color: Colors.white,
                              ),
                            ),
                          ],
                        ),
                      ),
                      if (searchController != null &&
                          onSearchChanged != null) ...[
                        const SizedBox(height: _subtitleToSearchGap),
                        LibrarySearchField(
                          controller: searchController!,
                          onChanged: onSearchChanged!,
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),
          ),
          // Outside the padded content so it can sit closer to the edge than
          // the header padding, and last so it stays on top and tappable.
          const Positioned.fill(
            child: SafeArea(
              bottom: false,
              child: Stack(
                children: [
                  Positioned(
                    top: topGap,
                    right: _bellRight,
                    child: ScanBell(iconSize: _bellIconSize),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// The large faded mark behind the header text. Ignores pointers and is
/// excluded from semantics so the title, search field and bell stay fully
/// tappable and readable (PIYA-205-V2.1 AC5).
class _BackdropLogo extends StatelessWidget {
  const _BackdropLogo();

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: ExcludeSemantics(
        child: SizedBox(
          key: const ValueKey('library-header-backdrop-logo'),
          width: LibraryHeader._backdropLogoWidth,
          height: LibraryHeader._backdropLogoHeight,
          child: Opacity(
            opacity: AppTheme.libraryHeaderLogoOpacity,
            child: OverflowBox(
              minWidth: LibraryHeader._backdropLogoCanvas,
              minHeight: LibraryHeader._backdropLogoCanvas,
              maxWidth: LibraryHeader._backdropLogoCanvas,
              maxHeight: LibraryHeader._backdropLogoCanvas,
              child: Image.asset(
                LibraryHeader._logoAsset,
                width: LibraryHeader._backdropLogoCanvas,
                height: LibraryHeader._backdropLogoCanvas,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// The faded corner mark. Public, with the title metrics above, so Settings
/// (PIYA-212) draws the same header instead of a lookalike copy.
class LibraryHeaderLogo extends StatelessWidget {
  const LibraryHeaderLogo({super.key});

  @override
  Widget build(BuildContext context) {
    return ExcludeSemantics(
      child: SizedBox(
        key: const ValueKey('library-header-logo'),
        width: LibraryHeader.logoMarkWidth,
        height: LibraryHeader._logoMarkHeight,
        child: Opacity(
          opacity: AppTheme.settingsHeaderLogoOpacity,
          child: OverflowBox(
            minWidth: LibraryHeader._logoCanvasSize,
            minHeight: LibraryHeader._logoCanvasSize,
            maxWidth: LibraryHeader._logoCanvasSize,
            maxHeight: LibraryHeader._logoCanvasSize,
            child: Image.asset(
              LibraryHeader._logoAsset,
              width: LibraryHeader._logoCanvasSize,
              height: LibraryHeader._logoCanvasSize,
            ),
          ),
        ),
      ),
    );
  }
}

/// The mockup's search box: no fill, a half-white 1 dp outline and white
/// text, so the header gradient shows through. A clear (x) button appears
/// once there is text.
class LibrarySearchField extends StatelessWidget {
  const LibrarySearchField({
    super.key,
    required this.controller,
    required this.onChanged,
  });

  final TextEditingController controller;
  final ValueChanged<String> onChanged;

  static const double _radius = 12;
  static const double _fontSize = 14;
  static const double _iconSize = 23;
  static const double _clearIconSize = 20;
  // Matches the mockup's 51 dp field height at 1x text scale; at larger
  // scales the field grows with the text instead of clipping it.
  static const EdgeInsets _contentPadding = EdgeInsets.symmetric(vertical: 15);
  static const EdgeInsets _iconPadding = EdgeInsets.only(left: 14, right: 8);

  void _clear() {
    // Clearing the controller doesn't fire onChanged, so report it
    // explicitly. Focus is untouched: the user can type a new query
    // straight away.
    controller.clear();
    onChanged('');
  }

  @override
  Widget build(BuildContext context) {
    final border = OutlineInputBorder(
      borderRadius: BorderRadius.circular(_radius),
      borderSide: BorderSide(
        color: Colors.white.withValues(
          alpha: AppTheme.librarySearchBorderAlpha,
        ),
      ),
    );
    final textStyle = Theme.of(context).textTheme.bodyLarge
        ?.copyWith(fontSize: _fontSize, color: Colors.white);

    return ValueListenableBuilder<TextEditingValue>(
      valueListenable: controller,
      builder: (context, value, _) => TextField(
        controller: controller,
        onChanged: onChanged,
        style: textStyle,
        cursorColor: Colors.white,
        textInputAction: TextInputAction.search,
        decoration: InputDecoration(
          isDense: true,
          hintText: LibraryMessages.searchHint,
          hintStyle: textStyle?.copyWith(
            color: Colors.white.withValues(
              alpha: AppTheme.librarySearchHintAlpha,
            ),
          ),
          prefixIcon: const Padding(
            padding: _iconPadding,
            child: Icon(
              Icons.search_rounded,
              color: Colors.white,
              size: _iconSize,
            ),
          ),
          prefixIconConstraints: const BoxConstraints(),
          suffixIcon: value.text.isEmpty
              ? null
              : IconButton(
                  key: const ValueKey('library-search-clear'),
                  tooltip: LibraryMessages.clearSearch,
                  onPressed: _clear,
                  icon: const Icon(
                    Icons.close_rounded,
                    color: Colors.white,
                    size: _clearIconSize,
                  ),
                ),
          contentPadding: _contentPadding,
          filled: false,
          border: border,
          enabledBorder: border,
          // Focus is shown by a fully opaque outline rather than Material's
          // primary-coloured one, which would vanish against the blue header.
          focusedBorder: border.copyWith(
            borderSide: const BorderSide(color: Colors.white, width: 1.5),
          ),
        ),
      ),
    );
  }
}
