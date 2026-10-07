import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';
import '../library_messages.dart';

/// Gradient top section of the Score Library mockup: centred logo mark,
/// "My Scores", a status subtitle and the outlined search field.
///
/// Dimensions are read off the 412 dp-wide mockup (1 px = 1 dp there).
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
  // The logo PNG's mark fills only ~62% of its square canvas height, so the
  // canvas is drawn larger and overflows a box sized to the mark itself
  // (49 dp tall in the mockup), keeping the spacing around it exact.
  static const double _logoMarkHeight = 49;
  static const double _logoCanvasSize = 80;

  static const double _topGap = 2;
  static const double _logoToTitleGap = 10;
  static const double _subtitleToSearchGap = 10;
  static const double _bottomGap = 16;
  static const double _titleFontSize = 34;
  static const double _subtitleFontSize = 15;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return DecoratedBox(
      decoration: const BoxDecoration(
        gradient: AppTheme.libraryHeaderGradient,
      ),
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: EdgeInsets.fromLTRB(
            horizontalPadding,
            _topGap,
            horizontalPadding,
            _bottomGap,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              ExcludeSemantics(
                child: SizedBox(
                  height: _logoMarkHeight,
                  child: OverflowBox(
                    // Explicit minimums: the stretched Column would
                    // otherwise pass its full width down as the minimum.
                    minWidth: _logoCanvasSize,
                    minHeight: _logoCanvasSize,
                    maxWidth: _logoCanvasSize,
                    maxHeight: _logoCanvasSize,
                    child: Image.asset(
                      _logoAsset,
                      width: _logoCanvasSize,
                      height: _logoCanvasSize,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: _logoToTitleGap),
              Semantics(
                header: true,
                child: Text(
                  LibraryMessages.title,
                  style: textTheme.headlineLarge?.copyWith(
                    fontSize: _titleFontSize,
                    fontWeight: FontWeight.w700,
                    height: 1.2,
                    color: Colors.white,
                  ),
                ),
              ),
              Text(
                subtitle,
                style: textTheme.bodyLarge?.copyWith(
                  fontSize: _subtitleFontSize,
                  height: 1.25,
                  color: Colors.white,
                ),
              ),
              const SizedBox(height: _subtitleToSearchGap),
              LibrarySearchField(
                controller: searchController,
                onChanged: onSearchChanged,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The mockup's search box: no fill, a half-white 1 dp outline and white
/// text, so the header gradient shows through.
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
  // Matches the mockup's 51 dp field height at 1x text scale; at larger
  // scales the field grows with the text instead of clipping it.
  static const EdgeInsets _contentPadding = EdgeInsets.symmetric(vertical: 15);
  static const EdgeInsets _iconPadding = EdgeInsets.only(left: 14, right: 8);

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
    final textStyle = Theme.of(context).textTheme.bodyLarge?.copyWith(
          fontSize: _fontSize,
          color: Colors.white,
        );

    return TextField(
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
          child: Icon(Icons.search_rounded, color: Colors.white, size: _iconSize),
        ),
        prefixIconConstraints: const BoxConstraints(),
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
    );
  }
}
