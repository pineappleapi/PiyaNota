import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/capture_page.dart';
import '../../state/capture_providers.dart';
import '../../theme/app_theme.dart';
import 'capture_messages.dart';

/// Full-screen look at one page (tap on a thumbnail), with pinch-zoom so a
/// singer can check the notes are sharp before sending. A PDF shows its
/// name and page count; its pages are rendered on the server.
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
    final textTheme = Theme.of(context).textTheme;
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
                image: ref.read(pageImageSourceProvider).imageFor(item.path),
                fit: BoxFit.contain,
                semanticLabel: CaptureMessages.pageOf(number, total),
              ),
            ),
          ),
          PdfDocument() => Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.picture_as_pdf_outlined,
                    size: 72,
                    color: AppTheme.captureAccent,
                  ),
                  const SizedBox(height: 12),
                  Text(
                    item.name,
                    textAlign: TextAlign.center,
                    style: textTheme.titleMedium?.copyWith(
                      color: Colors.white,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    CaptureMessages.pagesLabel(item.pages),
                    style: textTheme.bodyMedium?.copyWith(color: Colors.white),
                  ),
                ],
              ),
            ),
          ),
        },
      ),
    );
  }
}
