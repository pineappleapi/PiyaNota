import 'package:flutter/material.dart';

import '../../../models/score_summary.dart';
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
  // Keeps titles clear of the chevron (top-right) and trash (bottom-right).
  static const double rightReserve = 40;
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
    required this.score,
    required this.onTap,
    required this.onDelete,
    this.isDeleting = false,
  });

  final ScoreSummary score;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  /// While a delete request is in flight the trash shows a spinner and both
  /// taps are disabled, so the user can't open a score that is about to
  /// disappear or fire a second delete.
  final bool isDeleting;

  static const double _titleSize = 18;
  static const double _subtitleSize = 13;
  static const double _noteIconSize = 38;
  static const double _chevronSize = 18;
  static const double _chevronInset = 8;
  static const double _trashSize = 16;
  static const double _spinnerSize = 14;
  static const double _spinnerStroke = 2;
  // A 48x41 dp hit area (the card's lower-right half) around a 16 dp glyph
  // placed where the mockup draws it: 10 dp from the right, 7 from the
  // bottom.
  static const double _trashHitWidth = 48;
  static const double _trashHitHeight = 41;
  static const EdgeInsets _trashGlyphInset = EdgeInsets.only(
    right: 10,
    bottom: 7,
  );

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
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
          width: _trashHitWidth,
          height: _trashHitHeight,
          child: Semantics(
            button: true,
            label: LibraryMessages.deleteSemantics(score.title),
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
        child: _CardRow(
          tileColor: Colors.white,
          tile: const Icon(
            Icons.music_note_outlined,
            size: _noteIconSize,
            color: AppTheme.libraryIconBlue,
          ),
          text: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                score.title,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: textTheme.titleMedium?.copyWith(
                  fontSize: _titleSize,
                  fontWeight: FontWeight.w700,
                  height: 1.2,
                  color: AppTheme.libraryCardTitle,
                ),
              ),
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

/// Loading placeholder in the score-card style (AC5). Static rather than
/// shimmering: a looping animation adds nothing on a sub-second fake fetch
/// and would keep the frame scheduler busy for no benefit.
class ScoreCardSkeleton extends StatelessWidget {
  const ScoreCardSkeleton({super.key});

  static const double _barHeight = 12;
  static const double _titleBarFraction = 0.75;
  static const double _subtitleBarFraction = 0.5;
  static const double _barGap = 10;
  static const double _barRadius = 6;
  static const double _barAlpha = 0.7;

  @override
  Widget build(BuildContext context) {
    final barColor = Colors.white.withValues(alpha: _barAlpha);
    Widget bar(double fraction) => FractionallySizedBox(
          alignment: Alignment.centerLeft,
          widthFactor: fraction,
          child: Container(
            height: _barHeight,
            decoration: BoxDecoration(
              color: barColor,
              borderRadius: BorderRadius.circular(_barRadius),
            ),
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
    canvas.drawLine(Offset(mid, inset), Offset(mid, size.height - inset), paint);
    canvas.drawLine(Offset(inset, mid), Offset(size.width - inset, mid), paint);
  }

  @override
  bool shouldRepaint(_PlusPainter oldDelegate) => false;
}
