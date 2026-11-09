import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/capture_page.dart';
import '../../services/capture/device_channel.dart';
import '../../services/capture/page_image_source.dart';
import '../../services/capture/pdf_page_renderer.dart';
import '../../state/capture_providers.dart';
import '../../theme/app_theme.dart';
import 'capture_messages.dart';

/// Full-screen look at one page (tap on a thumbnail), with pinch-zoom so a
/// singer can check the notes are sharp before sending. A PDF shows its
/// name, page count and a lazily rendered list of its pages.
class PagePreviewScreen extends ConsumerWidget {
  const PagePreviewScreen({
    super.key,
    required this.item,
    required this.number,
    required this.total,
  });

  final CaptureItem item;
  final int number;
  final int total;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final item = this.item;
    return Scaffold(
      backgroundColor: AppTheme.captureInk,
      appBar: AppBar(
        backgroundColor: AppTheme.captureInk,
        foregroundColor: Colors.white,
        title: Text(
          item is PdfDocument
              ? CaptureMessages.pdfCard(item.pages)
              : CaptureMessages.pageOf(number, total),
        ),
        leading: IconButton(
          tooltip: CaptureMessages.close,
          icon: const Icon(Icons.close_rounded),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: SafeArea(
        child: switch (item) {
          PhotoPage() => InteractiveViewer(
            maxScale: 6,
            child: Center(
              child: Image(
                image: capToDisplay(
                  ref.read(pageImageSourceProvider).imageFor(item.path),
                  logicalSide: MediaQuery.sizeOf(context).longestSide,
                  devicePixelRatio: MediaQuery.devicePixelRatioOf(context),
                ),
                fit: BoxFit.contain,
                semanticLabel: CaptureMessages.pageOf(number, total),
              ),
            ),
          ),
          PdfDocument() => _PdfPages(pdf: item),
        },
      ),
    );
  }
}

/// Widest render of a PDF page, in pixels: thumbnail-sized so a 20-page
/// score never holds 20 full-resolution bitmaps.
const double _maxPageRenderWidth = 720;
const double _pdfPadding = 16;

/// A4 portrait: the placeholder height until a page has rendered.
const double _placeholderAspect = 1.414;

class _PdfPages extends ConsumerStatefulWidget {
  const _PdfPages({required this.pdf});

  final PdfDocument pdf;

  @override
  ConsumerState<_PdfPages> createState() => _PdfPagesState();
}

class _PdfPagesState extends ConsumerState<_PdfPages> {
  late final Future<PdfPreviewDocument> _document;

  /// One render per page, kept so scrolling back doesn't redo it.
  final Map<int, Future<Uint8List>> _renders = {};

  @override
  void initState() {
    super.initState();
    _document = ref.read(pdfPageRendererProvider).open(widget.pdf.path);
  }

  @override
  void dispose() {
    // A failed open has nothing to close.
    _document.then<void>((doc) => doc.close(), onError: (Object _) {});
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final renderWidth =
        (MediaQuery.sizeOf(context).width *
                MediaQuery.devicePixelRatioOf(context))
            .clamp(1, _maxPageRenderWidth)
            .toDouble();
    return FutureBuilder<PdfPreviewDocument>(
      future: _document,
      builder: (context, snapshot) {
        final error = snapshot.error;
        if (error != null) {
          return _Note(
            error is PdfUnreadableException
                ? CaptureMessages.pdfProblem(error.problem)
                : CaptureMessages.pdfCorrupt,
          );
        }
        final doc = snapshot.data;
        if (doc == null) {
          return const Center(child: CircularProgressIndicator());
        }
        return ListView.builder(
          padding: const EdgeInsets.all(_pdfPadding),
          // Item 0 is the name and page count; pages follow.
          itemCount: doc.pageCount + 1,
          itemBuilder: (context, i) {
            if (i == 0) {
              return Padding(
                padding: const EdgeInsets.only(bottom: _pdfPadding),
                child: Column(
                  children: [
                    Text(
                      widget.pdf.name,
                      textAlign: TextAlign.center,
                      style: textTheme.titleMedium?.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text(
                      CaptureMessages.pagesLabel(doc.pageCount),
                      style: textTheme.bodyMedium?.copyWith(
                        color: Colors.white,
                      ),
                    ),
                  ],
                ),
              );
            }
            final index = i - 1;
            final render = _renders.putIfAbsent(
              index,
              () => doc.renderPage(index, width: renderWidth),
            );
            return Padding(
              padding: const EdgeInsets.only(bottom: _pdfPadding),
              child: FutureBuilder<Uint8List>(
                future: render,
                builder: (context, page) {
                  final bytes = page.data;
                  if (bytes != null) {
                    return Image.memory(
                      bytes,
                      fit: BoxFit.fitWidth,
                      semanticLabel: CaptureMessages.pageOf(
                        index + 1,
                        doc.pageCount,
                      ),
                      // An undecoded image is 0 high, which would make the
                      // list build every page at once; hold the A4 slot.
                      frameBuilder: (context, child, frame, sync) =>
                          frame == null
                          ? const _PageSlot(child: SizedBox.shrink())
                          : child,
                    );
                  }
                  return _PageSlot(
                    child: page.hasError
                        ? const _Note(CaptureMessages.pageNotShown)
                        : const CircularProgressIndicator(),
                  );
                },
              ),
            );
          },
        );
      },
    );
  }
}

class _PageSlot extends StatelessWidget {
  const _PageSlot({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => AspectRatio(
    aspectRatio: 1 / _placeholderAspect,
    child: ColoredBox(
      color: Colors.white12,
      child: Center(child: child),
    ),
  );
}

class _Note extends StatelessWidget {
  const _Note(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Text(
        text,
        textAlign: TextAlign.center,
        style: Theme.of(context).textTheme.bodyMedium
            ?.copyWith(color: Colors.white),
      ),
    ),
  );
}
