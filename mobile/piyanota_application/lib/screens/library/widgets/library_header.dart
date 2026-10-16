import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';
import '../../scan_status/scan_bell.dart';
import '../library_messages.dart';

/// Gradient top section of the Score Library: "My Scores" and a status
/// subtitle on the left, the faded logo mark in the top-right corner (as on
/// Login/Sign-Up), then the outlined search field.
///
/// Dimensions are read off the 412 dp-wide mockup (1 px = 1 dp there),
/// except the logo, which the user moved out of the mockup's centred,
/// edge-hugging spot (round-2 review, 2026-10-08).
class LibraryHeader extends StatelessWidget {
  const LibraryHeader({
    super.key,
    required this.subtitle,
    required this.searchController,
    required this.onSearchChanged,
    required this.horizontalPadding,
  });

  final String subtitle;
  final TextEditingController searchController;
  final ValueChanged<String> onSearchChanged;
  final double horizontalPadding;

  static const String _logoAsset = 'assets/branding/Piyanota_App_Logo.png';
  // The PNG's mark spans x 528–1450, y 398–1631 of its 2000 px canvas
  // (measured from the alpha channel), so the canvas is drawn larger than
  // the box and overflows it, leaving the box the size of the mark itself.
  // That lets the mark's top and right edges line up with the safe-area gap
  // and the search field's right edge exactly.
  static const double _logoMarkHeight = 72;
  static const double _logoMarkWidth = 54;
  // 72 / 0.6165 (mark height fraction). The mark is centred on the canvas
  // to within 1 dp, so OverflowBox's default centring needs no offset.
  static const double _logoCanvasSize = 117;

  /// Breathing room between the status bar (safe area) and the header
  /// content, so neither the logo nor the title touches the top edge.
  static const double topGap = 12;
  static const double _titleToLogoGap = 12;
  static const double _bellToLogoGap = 4;

  /// Title top below the safe area, as in round 1 (61f5583): its 2 dp top
  /// gap + the 49 dp centred mark + a 10 dp gap. The mark has since moved
  /// to the corner, but the user asked to keep the text where it was
  /// (2026-10-08), so the offset stays even though the space is now empty.
  static const double _titleTop = 61;
  static const double _subtitleToSearchGap = 10;
  static const double _bottomGap = 16;
  static const double _titleFontSize = 34;
  static const double _titleLineHeight = 1.2;
  static const double _subtitleLineHeight = 1.25;

  /// The 34 sp heading and its subtitle stop growing past 1.5x. Android 14+
  /// already scales large text nonlinearly (a 34 sp title at 200% renders
  /// near 1.5x), and on a 320 dp phone at a linear 2x the heading alone
  /// filled the screen and pushed the list out of view (NFR-10). The search
  /// field and the cards keep the full system scale.
  static const double _headingMaxTextScale = 1.5;

  /// Above this scale the decorative mark is dropped so the heading gets
  /// the full width instead of wrapping word-by-word beside it.
  static const double _logoMaxTextScale = 1.3;
  static const double _subtitleFontSize = 15;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final textScale =
        MediaQuery.textScalerOf(context).scale(_subtitleFontSize) /
        _subtitleFontSize;
    final showLogo = textScale <= _logoMaxTextScale;

    return DecoratedBox(
      decoration: const BoxDecoration(gradient: AppTheme.libraryHeaderGradient),
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: EdgeInsets.fromLTRB(
            horizontalPadding,
            topGap,
            horizontalPadding,
            _bottomGap,
          ),
          // The mark is laid out on its own layer so it can never move the
          // title or the search field.
          child: Stack(
            children: [
              if (showLogo)
                const Positioned(top: 0, right: 0, child: _HeaderLogo()),
              // PIYA-218 AC5. With the mark shown, the bell sits in the
              // empty band above the title, just left of the mark; without
              // it, in the title's row at the right edge.
              Positioned(
                top: 0,
                right: showLogo ? _logoMarkWidth + _bellToLogoGap : 0,
                child: const ScanBell(),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // Round-1 position at normal sizes. At large text the
                  // mark is hidden and its band is dropped too, so on a
                  // 320 dp phone at 2x the results stay in view (NFR-10).
                  SizedBox(height: showLogo ? _titleTop - topGap : 0),
                  MediaQuery.withClampedTextScaling(
                    maxScaleFactor: _headingMaxTextScale,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Padding(
                          // Only the title shares a band with the mark (it
                          // ends 72 dp down); the subtitle is below it and
                          // keeps the full width.
                          padding: EdgeInsets.only(
                            right: showLogo
                                ? _logoMarkWidth + _titleToLogoGap
                                : ScanBell.size + _titleToLogoGap,
                          ),
                          child: Semantics(
                            header: true,
                            child: Text(
                              LibraryMessages.title,
                              style: textTheme.headlineLarge?.copyWith(
                                fontSize: _titleFontSize,
                                fontWeight: FontWeight.w700,
                                height: _titleLineHeight,
                                color: Colors.white,
                              ),
                            ),
                          ),
                        ),
                        Text(
                          subtitle,
                          style: textTheme.bodyLarge?.copyWith(
                            fontSize: _subtitleFontSize,
                            height: _subtitleLineHeight,
                            color: Colors.white,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: _subtitleToSearchGap),
                  LibrarySearchField(
                    controller: searchController,
                    onChanged: onSearchChanged,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _HeaderLogo extends StatelessWidget {
  const _HeaderLogo();

  @override
  Widget build(BuildContext context) {
    return ExcludeSemantics(
      child: SizedBox(
        key: const ValueKey('library-header-logo'),
        width: LibraryHeader._logoMarkWidth,
        height: LibraryHeader._logoMarkHeight,
        child: Opacity(
          opacity: AppTheme.libraryHeaderLogoOpacity,
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
