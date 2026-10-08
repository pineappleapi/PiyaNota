import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';

import '../../../models/capture_page.dart';
import '../../../services/capture/page_image_source.dart';
import '../../../theme/app_theme.dart';
import '../capture_messages.dart';

/// The reorderable thumbnail strip (AC4, AC5): long-press drag to reorder,
/// ✎ to edit, 🗑 to remove, tap to preview, and a trailing "+" tile. ‹ ›
/// arrows appear only when the pages don't all fit, and fade at the ends.
class PageStrip extends StatefulWidget {
  const PageStrip({
    super.key,
    required this.items,
    required this.imageSource,
    required this.onReorder,
    required this.onOpen,
    required this.onEdit,
    required this.onRemove,
    required this.onAdd,
    this.flashId,
    this.enabled = true,
  });

  final List<CaptureItem> items;
  final PageImageSource imageSource;

  /// [ReorderableListView] convention for `newIndex`.
  final void Function(int oldIndex, int newIndex) onReorder;
  final ValueChanged<CaptureItem> onOpen;
  final ValueChanged<PhotoPage> onEdit;
  final ValueChanged<CaptureItem> onRemove;
  final VoidCallback? onAdd;

  /// A just-added item, flashed once and scrolled into view.
  final int? flashId;
  final bool enabled;

  static const double thumbWidth = 84;
  static const double thumbHeight = 112;
  static const double height = thumbHeight + 8;
  static const double gap = 10;

  @override
  State<PageStrip> createState() => _PageStripState();
}

class _PageStripState extends State<PageStrip> {
  final _scroll = ScrollController();
  bool _canLeft = false;
  bool _canRight = false;
  bool _overflows = false;

  static const Duration _arrowFade = Duration(milliseconds: 180);
  static const Duration _scrollDuration = Duration(milliseconds: 300);

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_updateArrows);
    WidgetsBinding.instance.addPostFrameCallback((_) => _updateArrows());
  }

  @override
  void didUpdateWidget(PageStrip oldWidget) {
    super.didUpdateWidget(oldWidget);
    final flash = widget.flashId;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _updateArrows();
      if (flash != null && flash != oldWidget.flashId) _revealFlashed(flash);
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _updateArrows() {
    if (!_scroll.hasClients) return;
    final p = _scroll.position;
    if (!p.hasContentDimensions) return;
    final overflows = p.maxScrollExtent > 0;
    final left = overflows && p.pixels > p.minScrollExtent + 1;
    final right = overflows && p.pixels < p.maxScrollExtent - 1;
    if (overflows != _overflows || left != _canLeft || right != _canRight) {
      setState(() {
        _overflows = overflows;
        _canLeft = left;
        _canRight = right;
      });
    }
  }

  void _revealFlashed(int id) {
    if (!_scroll.hasClients) return;
    final index = widget.items.indexWhere((item) => item.id == id);
    if (index < 0) return;
    final p = _scroll.position;
    const slot = PageStrip.thumbWidth + PageStrip.gap;
    final start = index * slot;
    final end = start + slot;
    double? target;
    if (start < p.pixels) {
      target = start;
    } else if (end > p.pixels + p.viewportDimension) {
      target = end - p.viewportDimension;
    }
    if (target == null) return;
    _scroll.animateTo(
      target.clamp(p.minScrollExtent, p.maxScrollExtent),
      duration: _scrollDuration,
      curve: Curves.easeOut,
    );
  }

  /// About one viewport per tap, less one slot so the last thumbnail seen
  /// stays on screen as a landmark.
  void _page(int direction) {
    final p = _scroll.position;
    const slot = PageStrip.thumbWidth + PageStrip.gap;
    final step = (p.viewportDimension - slot).clamp(slot, double.infinity);
    _scroll.animateTo(
      (p.pixels + direction * step).clamp(p.minScrollExtent, p.maxScrollExtent),
      duration: _scrollDuration,
      curve: Curves.easeOut,
    );
  }

  @override
  Widget build(BuildContext context) {
    final items = widget.items;
    final photoCount = items.length;
    return SizedBox(
      height: PageStrip.height,
      child: Stack(
        children: [
          NotificationListener<ScrollMetricsNotification>(
            onNotification: (_) {
              WidgetsBinding.instance.addPostFrameCallback(
                (_) => _updateArrows(),
              );
              return false;
            },
            child: ReorderableListView.builder(
              scrollController: _scroll,
              scrollDirection: Axis.horizontal,
              buildDefaultDragHandles: false,
              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
              itemCount: items.length,
              // onReorderItem reports the final index; the session keeps
              // the older "index before removal" convention.
              onReorderItem: (oldIndex, newIndex) => widget.onReorder(
                oldIndex,
                newIndex > oldIndex ? newIndex + 1 : newIndex,
              ),
              proxyDecorator: (child, _, _) =>
                  Material(color: Colors.transparent, child: child),
              footer: widget.onAdd == null
                  ? null
                  : _AddTile(onTap: widget.enabled ? widget.onAdd : null),
              itemBuilder: (context, index) {
                final item = items[index];
                final thumb = switch (item) {
                  PhotoPage() => _PhotoThumb(
                    page: item,
                    number: index + 1,
                    total: photoCount,
                    imageSource: widget.imageSource,
                    flash: item.id == widget.flashId,
                    onOpen: () => widget.onOpen(item),
                    onEdit: widget.enabled ? () => widget.onEdit(item) : null,
                    onRemove: widget.enabled
                        ? () => widget.onRemove(item)
                        : null,
                    onMoveEarlier: widget.enabled && index > 0
                        ? () => widget.onReorder(index, index - 1)
                        : null,
                    onMoveLater: widget.enabled && index < items.length - 1
                        ? () => widget.onReorder(index, index + 2)
                        : null,
                  ),
                  PdfDocument() => _PdfThumb(
                    pdf: item,
                    flash: item.id == widget.flashId,
                    onOpen: () => widget.onOpen(item),
                    onRemove: widget.enabled
                        ? () => widget.onRemove(item)
                        : null,
                  ),
                };
                return Padding(
                  key: ValueKey(item.id),
                  padding: const EdgeInsets.only(right: PageStrip.gap),
                  child: widget.enabled && item is PhotoPage
                      ? ReorderableDelayedDragStartListener(
                          index: index,
                          child: thumb,
                        )
                      : thumb,
                );
              },
            ),
          ),
          if (_overflows) ...[
            Positioned(
              left: 0,
              top: 0,
              bottom: 0,
              child: _Arrow(
                visible: _canLeft,
                icon: Icons.chevron_left_rounded,
                tooltip: CaptureMessages.scrollLeft,
                onTap: () => _page(-1),
                duration: _arrowFade,
              ),
            ),
            Positioned(
              right: 0,
              top: 0,
              bottom: 0,
              child: _Arrow(
                visible: _canRight,
                icon: Icons.chevron_right_rounded,
                tooltip: CaptureMessages.scrollRight,
                onTap: () => _page(1),
                duration: _arrowFade,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _Arrow extends StatelessWidget {
  const _Arrow({
    required this.visible,
    required this.icon,
    required this.tooltip,
    required this.onTap,
    required this.duration,
  });

  final bool visible;
  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;
  final Duration duration;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: AnimatedOpacity(
        opacity: visible ? 1 : 0,
        duration: duration,
        child: IgnorePointer(
          ignoring: !visible,
          child: ExcludeSemantics(
            excluding: !visible,
            child: IconButton.filled(
              tooltip: tooltip,
              onPressed: onTap,
              style: IconButton.styleFrom(
                backgroundColor: AppTheme.captureInk,
                foregroundColor: AppTheme.captureAccent,
                minimumSize: const Size(48, 48),
              ),
              icon: Icon(icon),
            ),
          ),
        ),
      ),
    );
  }
}

/// Briefly lights a new thumbnail so the eye finds where it landed.
class _Flash extends StatefulWidget {
  const _Flash({required this.active, required this.child});

  final bool active;
  final Widget child;

  @override
  State<_Flash> createState() => _FlashState();
}

class _FlashState extends State<_Flash> with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 900),
    value: widget.active ? 1 : 0,
  );

  @override
  void initState() {
    super.initState();
    if (widget.active) _controller.reverse();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        widget.child,
        Positioned.fill(
          child: IgnorePointer(
            child: FadeTransition(
              opacity: _controller,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.55),
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _ThumbFrame extends StatelessWidget {
  const _ThumbFrame({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: PageStrip.thumbWidth,
      height: PageStrip.thumbHeight,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.captureAccent, width: 2),
      ),
      clipBehavior: Clip.antiAlias,
      child: child,
    );
  }
}

class _PhotoThumb extends StatelessWidget {
  const _PhotoThumb({
    required this.page,
    required this.number,
    required this.total,
    required this.imageSource,
    required this.flash,
    required this.onOpen,
    required this.onEdit,
    required this.onRemove,
    required this.onMoveEarlier,
    required this.onMoveLater,
  });

  final PhotoPage page;
  final int number;
  final int total;
  final PageImageSource imageSource;
  final bool flash;
  final VoidCallback onOpen;
  final VoidCallback? onEdit;
  final VoidCallback? onRemove;
  final VoidCallback? onMoveEarlier;
  final VoidCallback? onMoveLater;

  @override
  Widget build(BuildContext context) {
    return _Flash(
      active: flash,
      child: _ThumbFrame(
        child: Stack(
          fit: StackFit.expand,
          children: [
            Semantics(
              button: true,
              label: CaptureMessages.pageSemantics(number, total),
              customSemanticsActions: {
                const CustomSemanticsAction(label: CaptureMessages.moveEarlier):
                    ?onMoveEarlier,
                const CustomSemanticsAction(label: CaptureMessages.moveLater):
                    ?onMoveLater,
              },
              excludeSemantics: true,
              onTap: onOpen,
              child: InkWell(
                onTap: onOpen,
                child: Image(
                  image: imageSource.imageFor(page.path),
                  fit: BoxFit.cover,
                  gaplessPlayback: true,
                  errorBuilder: (_, _, _) => const Center(
                    child: Icon(
                      Icons.description_outlined,
                      size: 40,
                      color: AppTheme.captureThumbGlyph,
                    ),
                  ),
                ),
              ),
            ),
            Positioned(left: 4, top: 4, child: _Badge(text: '$number')),
            if (onEdit != null)
              Positioned(
                right: 0,
                top: 0,
                child: _DiscButton(
                  icon: Icons.edit_rounded,
                  tooltip: CaptureMessages.editPage(number),
                  onTap: onEdit!,
                  alignment: Alignment.topRight,
                ),
              ),
            if (onRemove != null)
              Positioned(
                right: 0,
                bottom: 0,
                child: _DiscButton(
                  icon: Icons.delete_outline_rounded,
                  tooltip: CaptureMessages.removePage(number),
                  onTap: onRemove!,
                  alignment: Alignment.bottomRight,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _PdfThumb extends StatelessWidget {
  const _PdfThumb({
    required this.pdf,
    required this.flash,
    required this.onOpen,
    required this.onRemove,
  });

  final PdfDocument pdf;
  final bool flash;
  final VoidCallback onOpen;
  final VoidCallback? onRemove;

  @override
  Widget build(BuildContext context) {
    return _Flash(
      active: flash,
      child: _ThumbFrame(
        child: Stack(
          fit: StackFit.expand,
          children: [
            Semantics(
              button: true,
              label: CaptureMessages.pdfSemantics(pdf.name, pdf.pages),
              excludeSemantics: true,
              onTap: onOpen,
              child: InkWell(
                onTap: onOpen,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(6, 10, 6, 6),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(
                        Icons.picture_as_pdf_outlined,
                        size: 32,
                        color: AppTheme.captureInk,
                      ),
                      const SizedBox(height: 4),
                      Expanded(
                        child: Text(
                          CaptureMessages.pdfCard(pdf.pages),
                          overflow: TextOverflow.fade,
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                            color: AppTheme.captureInk,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            if (onRemove != null)
              Positioned(
                right: 0,
                bottom: 0,
                child: _DiscButton(
                  icon: Icons.delete_outline_rounded,
                  tooltip: CaptureMessages.removePdf,
                  onTap: onRemove!,
                  alignment: Alignment.bottomRight,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return ExcludeSemantics(
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(
          color: AppTheme.captureInk,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          text,
          textScaler: TextScaler.noScaling,
          style: const TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w800,
            color: AppTheme.captureAccent,
          ),
        ),
      ),
    );
  }
}

/// A 48 dp tap target with a smaller navy disc drawn in its corner, so the
/// icon reads on any photo while the target stays full size.
class _DiscButton extends StatelessWidget {
  const _DiscButton({
    required this.icon,
    required this.tooltip,
    required this.onTap,
    required this.alignment,
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;
  final Alignment alignment;

  static const double _target = 48;
  static const double _disc = 28;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: tooltip,
      excludeSemantics: true,
      onTap: onTap,
      child: InkResponse(
        onTap: onTap,
        radius: _target / 2,
        child: SizedBox.square(
          dimension: _target,
          child: Align(
            alignment: alignment,
            child: Container(
              margin: const EdgeInsets.all(4),
              width: _disc,
              height: _disc,
              decoration: const BoxDecoration(
                color: AppTheme.captureInk,
                shape: BoxShape.circle,
              ),
              child: Icon(icon, size: 16, color: AppTheme.captureAccent),
            ),
          ),
        ),
      ),
    );
  }
}

class _AddTile extends StatelessWidget {
  const _AddTile({required this.onTap});

  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      enabled: onTap != null,
      label: CaptureMessages.addPages,
      excludeSemantics: true,
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.only(left: 0, right: 4),
        child: Material(
          color: AppTheme.captureInk.withValues(
            alpha: AppTheme.captureAddTileFillAlpha,
          ),
          borderRadius: BorderRadius.circular(10),
          child: InkWell(
            borderRadius: BorderRadius.circular(10),
            onTap: onTap,
            child: CustomPaint(
              painter: const _DashedBorderPainter(),
              child: const SizedBox(
                width: PageStrip.thumbWidth,
                height: PageStrip.thumbHeight,
                child: Icon(
                  Icons.add_rounded,
                  size: 36,
                  color: AppTheme.captureAccent,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _DashedBorderPainter extends CustomPainter {
  const _DashedBorderPainter();

  static const double _dash = 6;
  static const double _gap = 4;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppTheme.captureAccent
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2;
    final path = Path()
      ..addRRect(
        RRect.fromRectAndRadius(
          (Offset.zero & size).deflate(1),
          const Radius.circular(10),
        ),
      );
    for (final metric in path.computeMetrics()) {
      var distance = 0.0;
      while (distance < metric.length) {
        canvas.drawPath(metric.extractPath(distance, distance + _dash), paint);
        distance += _dash + _gap;
      }
    }
  }

  @override
  bool shouldRepaint(_DashedBorderPainter oldDelegate) => false;
}
