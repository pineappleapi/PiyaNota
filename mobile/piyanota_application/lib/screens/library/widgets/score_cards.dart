import 'package:flutter/material.dart';

import '../../../models/library_entry.dart';
import '../../../theme/app_theme.dart';
import '../library_messages.dart';

/// Card geometry shared by the Add Score card, score cards and loading
/// skeletons — all read off the 412 dp mockup, where every card is 82 dp
/// tall with a 50 dp icon tile inset 20 dp and the text 14 dp after it.
class _CardMetrics {
  _CardMetrics._();

  static const double minHeight = 82;
  static const double radius = 12;
  static const double outlineWidth = 1;
  static const double tileSize = 50;
  static const double tileRadius = 8;
  static const double leftInset = 20;
  static const double tileToText = 14;
  static const double verticalPadding = 12;
  // Keeps titles and subtitles clear of the chevron (top-right) and the
  // 48 dp trash target (bottom-right), so a tap on the text can never land
  // on Delete.
  static const double rightReserve = 48;
}

/// Outlined, rounded card body with the project's darken-on-press SOP
/// (frontend-piyanota.md "Interaction states") instead of a ripple.
class _CardShell extends StatelessWidget {
  const _CardShell({
    required this.fill,
    required this.child,
    this.onTap,
    this.overlays = const [],
  });

  final Color fill;
  final Widget child;
  final VoidCallback? onTap;
  final List<Widget> overlays;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: fill,
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(_CardMetrics.radius),
        side: const BorderSide(
          color: AppTheme.libraryCardOutline,
          width: _CardMetrics.outlineWidth,
        ),
      ),
      child: Stack(
        children: [
          InkWell(
            onTap: onTap,
            splashFactory: NoSplash.splashFactory,
            highlightColor: AppTheme.darken(fill),
            child: ConstrainedBox(
              constraints: const BoxConstraints(
                minHeight: _CardMetrics.minHeight,
              ),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(
                  _CardMetrics.leftInset,
                  _CardMetrics.verticalPadding,
                  _CardMetrics.rightReserve,
                  _CardMetrics.verticalPadding,
                ),
                child: child,
              ),
            ),
          ),
          ...overlays,
        ],
      ),
    );
  }
}

/// Icon tile + text column, vertically centred like the mockup.
class _CardRow extends StatelessWidget {
  const _CardRow({
    required this.tileColor,
    required this.tile,
    required this.text,
  });

  final Color tileColor;
  final Widget tile;
  final Widget text;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: _CardMetrics.tileSize,
          height: _CardMetrics.tileSize,
          decoration: BoxDecoration(
            color: tileColor,
            borderRadius: BorderRadius.circular(_CardMetrics.tileRadius),
          ),
          alignment: Alignment.center,
          child: tile,
        ),
        const SizedBox(width: _CardMetrics.tileToText),
        Expanded(child: text),
      ],
    );
  }
}

/// PIYA-205 AC8 entry point: the white "Add Score" card at the top of the
/// list.
class AddScoreCard extends StatelessWidget {
  const AddScoreCard({super.key, required this.onTap});

  final VoidCallback onTap;

  static const double _titleSize = 24;
  static const double _subtitleSize = 13;
  // The mockup's subtitle is visibly tracked tighter than the default.
  static const double _subtitleTracking = -0.3;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Semantics(
      button: true,
      child: _CardShell(
        fill: Colors.white,
        onTap: onTap,
        child: _CardRow(
          tileColor: AppTheme.libraryAddTileFill,
          tile: const _PlusGlyph(),
          text: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                LibraryMessages.addScoreTitle,
                style: textTheme.titleLarge?.copyWith(
                  fontSize: _titleSize,
                  fontWeight: FontWeight.w700,
                  height: 1.15,
                  color: AppTheme.libraryCardTitle,
                ),
              ),
              Text(
                LibraryMessages.addScoreSubtitle,
                style: textTheme.bodySmall?.copyWith(
                  fontSize: _subtitleSize,
                  letterSpacing: _subtitleTracking,
                  height: 1.25,
                  color: AppTheme.libraryAddSubtitle,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// One saved score. Tapping the card opens Playback (AC7); the trash icon
/// is its own tap target so deleting can never also open the score.
class ScoreCard extends StatelessWidget {
  const ScoreCard({
    super.key,
    required this.entry,
    required this.onTap,
    required this.onDelete,
    this.isDeleting = false,
  });

  final LibraryEntry entry;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  /// While a delete request is in flight the trash shows a spinner and both
  /// taps are disabled, so the user can't open a score that is about to
  /// disappear or fire a second delete.
  final bool isDeleting;

  static const double _titleSize = 18;
  // Slightly tighter than the mockup's 1.2 so a wrapped 2-line title reads
  // as one block (round-2 design polish).
  static const double _titleLineHeight = 1.15;
  // 12 sp (was the mockup's 13) per the user's "smaller, modern" request;
  // #575757 on the card fill is ~5.2:1, still WCAG AA for small text.
  static const double _subtitleSize = 12;
  static const double _chevronSize = 18;
  static const double _chevronInset = 8;
  static const double _trashSize = 16;
  static const double _spinnerSize = 14;
  static const double _spinnerStroke = 2;
  // A 48x48 dp hit area (Android's minimum tap target) in the card's
  // lower-right corner, around a 16 dp glyph placed where the mockup draws
  // it: 10 dp from the right, 7 from the bottom. On the 82 dp card it ends
  // well below the chevron.
  static const double _trashHitSize = 48;
  static const EdgeInsets _trashGlyphInset = EdgeInsets.only(
    right: 10,
    bottom: 7,
  );

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final score = entry.score;
    final subtitle = LibraryMessages.cardSubtitle(score);

    return _CardShell(
      fill: AppTheme.libraryScoreCardFill,
      onTap: isDeleting ? null : onTap,
      overlays: [
        const Positioned(
          top: _chevronInset,
          right: _chevronInset,
          child: ExcludeSemantics(
            child: Icon(
              Icons.chevron_right_rounded,
              size: _chevronSize,
              color: AppTheme.libraryCardTitle,
            ),
          ),
        ),
        Positioned(
          right: 0,
          bottom: 0,
          width: _trashHitSize,
          height: _trashHitSize,
          child: Semantics(
            button: true,
            enabled: !isDeleting,
            label: isDeleting
                ? LibraryMessages.deleting
                : LibraryMessages.deleteSemantics(entry.displayTitle),
            onTap: isDeleting ? null : onDelete,
            excludeSemantics: true,
            child: InkWell(
              onTap: isDeleting ? null : onDelete,
              splashFactory: NoSplash.splashFactory,
              highlightColor: AppTheme.darken(AppTheme.libraryScoreCardFill),
              child: Padding(
                padding: _trashGlyphInset,
                child: Align(
                  alignment: Alignment.bottomRight,
                  child: isDeleting
                      ? const SizedBox.square(
                          dimension: _spinnerSize,
                          child: CircularProgressIndicator(
                            strokeWidth: _spinnerStroke,
                            color: AppTheme.libraryTrash,
                            semanticsLabel: LibraryMessages.deleting,
                          ),
                        )
                      : const Icon(
                          Icons.delete_rounded,
                          size: _trashSize,
                          color: AppTheme.libraryTrash,
                        ),
                ),
              ),
            ),
          ),
        ),
      ],
      child: Semantics(
        button: true,
        enabled: !isDeleting,
        child: _CardRow(
          tileColor: Colors.white,
          tile: ScoreThumbnail(url: score.thumbnailUrl),
          text: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                entry.displayTitle,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: textTheme.titleMedium?.copyWith(
                  fontSize: _titleSize,
                  fontWeight: FontWeight.w700,
                  height: _titleLineHeight,
                  color: AppTheme.libraryCardTitle,
                ),
              ),
              // Left out entirely when every part is missing, rather than
              // leaving an empty line under the title.
              if (subtitle.isNotEmpty)
                Text(
                  subtitle,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: textTheme.bodySmall?.copyWith(
                    fontSize: _subtitleSize,
                    height: 1.3,
                    color: AppTheme.libraryScoreSubtitle,
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The score's thumbnail when the API supplies one and it loads; otherwise
/// (no URL, still loading, or a failed load) the mockup's music-note glyph,
/// so a broken image never leaves an empty tile.
class ScoreThumbnail extends StatelessWidget {
  const ScoreThumbnail({super.key, required this.url});

  final String? url;

  static const double _noteIconSize = 38;

  static const Widget _fallback = Icon(
    Icons.music_note_outlined,
    key: ValueKey('score-thumbnail-fallback'),
    size: _noteIconSize,
    color: AppTheme.libraryIconBlue,
  );

  @override
  Widget build(BuildContext context) {
    final url = this.url;
    if (url == null) return _fallback;
    final cacheSize =
        (_CardMetrics.tileSize * MediaQuery.devicePixelRatioOf(context))
            .round();
    return ClipRRect(
      borderRadius: BorderRadius.circular(_CardMetrics.tileRadius),
      child: Image.network(
        url,
        width: _CardMetrics.tileSize,
        height: _CardMetrics.tileSize,
        fit: BoxFit.cover,
        // Decode at tile size, not the source resolution, so a long library
        // of page-sized thumbnails doesn't balloon memory.
        cacheWidth: cacheSize,
        excludeFromSemantics: true,
        loadingBuilder: (context, child, progress) =>
            progress == null ? child : _fallback,
        errorBuilder: (context, error, stackTrace) => _fallback,
      ),
    );
  }
}

/// Loading placeholder in the score-card style (AC5), with a light shimmer
/// band sweeping across the bars.
///
/// The sweep is bounded to a few passes and then rests static, so a slow
/// network doesn't keep the frame scheduler busy indefinitely (and widget
/// tests' pumpAndSettle still settles). With reduce motion
/// (MediaQuery.disableAnimations) it never starts.
class ScoreCardSkeleton extends StatefulWidget {
  const ScoreCardSkeleton({super.key});

  @override
  State<ScoreCardSkeleton> createState() => ScoreCardSkeletonState();
}

@visibleForTesting
class ScoreCardSkeletonState extends State<ScoreCardSkeleton>
    with SingleTickerProviderStateMixin {
  static const double _barHeight = 12;
  static const double _titleBarFraction = 0.75;
  static const double _subtitleBarFraction = 0.5;
  static const double _barGap = 10;
  static const double _barRadius = 6;
  static const Duration _sweepDuration = Duration(milliseconds: 1400);
  static const int _maxSweeps = 5;
  // Half-width of the highlight band, as a fraction of the bar's width.
  static const double _bandHalfWidth = 0.15;

  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: _sweepDuration,
  );
  int _sweeps = 0;
  bool _started = false;

  /// For tests: whether the shimmer is currently running.
  bool get isShimmering => _controller.isAnimating;

  @override
  void initState() {
    super.initState();
    _controller.addStatusListener((status) {
      if (status != AnimationStatus.completed) return;
      _sweeps++;
      if (_sweeps < _maxSweeps) {
        _controller.forward(from: 0);
      } else {
        // Rest with the band off-bar, i.e. the plain static skeleton.
        _controller.value = 0;
      }
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.disableAnimationsOf(context)) {
      _controller.stop();
      _controller.value = 0;
    } else if (!_started) {
      _started = true;
      _controller.forward();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final baseColor = Colors.white.withValues(
      alpha: AppTheme.librarySkeletonBaseAlpha,
    );
    final highlightColor = Colors.white.withValues(
      alpha: AppTheme.librarySkeletonHighlightAlpha,
    );

    Widget bar(double fraction) => FractionallySizedBox(
      alignment: Alignment.centerLeft,
      widthFactor: fraction,
      child: AnimatedBuilder(
        animation: _controller,
        builder: (context, _) {
          // At t = 0 (and when resting) the band sits fully left of the
          // bar, so the bar is the plain base colour.
          final centre =
              -_bandHalfWidth + _controller.value * (1 + 2 * _bandHalfWidth);
          return Container(
            height: _barHeight,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(_barRadius),
              gradient: LinearGradient(
                colors: [baseColor, highlightColor, baseColor],
                stops: [
                  centre - _bandHalfWidth,
                  centre,
                  centre + _bandHalfWidth,
                ],
              ),
            ),
          );
        },
      ),
    );

    return _CardShell(
      fill: AppTheme.libraryScoreCardFill,
      child: _CardRow(
        tileColor: Colors.white,
        tile: const SizedBox.shrink(),
        text: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            bar(_titleBarFraction),
            const SizedBox(height: _barGap),
            bar(_subtitleBarFraction),
          ],
        ),
      ),
    );
  }
}

/// The Add Score tile's thin, round-capped "+", drawn rather than taken
/// from Icons.add: at the mockup's 31 dp span Material's glyph would need a
/// 53 dp icon box (overflowing the 50 dp tile) and its stroke is heavier.
class _PlusGlyph extends StatelessWidget {
  const _PlusGlyph();

  static const double _span = 31;

  @override
  Widget build(BuildContext context) {
    return const SizedBox.square(
      dimension: _span,
      child: CustomPaint(painter: _PlusPainter()),
    );
  }
}

class _PlusPainter extends CustomPainter {
  const _PlusPainter();

  static const double _stroke = 4;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppTheme.libraryIconBlue
      ..strokeWidth = _stroke
      ..strokeCap = StrokeCap.round;
    // Inset by half the stroke so the round caps end exactly at the span.
    const inset = _stroke / 2;
    final mid = size.width / 2;
    canvas.drawLine(
      Offset(mid, inset),
      Offset(mid, size.height - inset),
      paint,
    );
    canvas.drawLine(Offset(inset, mid), Offset(size.width - inset, mid), paint);
  }

  @override
  bool shouldRepaint(_PlusPainter oldDelegate) => false;
}
