import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/capture_page.dart';
import '../../models/capture_session.dart';
import '../../models/score_details.dart';
import '../../routes/app_routes.dart';
import '../../services/capture/capture_camera.dart';
import '../../services/capture/capture_permissions.dart';
import '../../services/capture/device_channel.dart';
import '../../services/capture/page_image_processor.dart';
import '../../services/capture/page_picker.dart';
import '../../services/score_upload_api.dart';
import '../../state/auth_providers.dart';
import '../../state/capture_providers.dart';
import '../../state/score_library_providers.dart';
import '../../theme/app_theme.dart';
import '../../widgets/primary_pill_button.dart';
import 'capture_messages.dart';
import 'edit_page_screen.dart';
import 'page_preview_screen.dart';
import 'widgets/camera_frame.dart';
import 'widgets/page_strip.dart';

/// Step 2 of Add Score (PIYA-206): photograph pages, or add them from the
/// gallery or a PDF, arrange them, and send. Capture-then-process only —
/// nothing is recognised live (SOW §4).
class CaptureScreen extends ConsumerStatefulWidget {
  const CaptureScreen({super.key, required this.details});

  final ScoreDetails details;

  @override
  ConsumerState<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends ConsumerState<CaptureScreen>
    with WidgetsBindingObserver {
  CaptureSession _session = const CaptureSession();
  int _nextId = 0;

  /// The page "Page X of N" talks about: the last one added or moved.
  int? _focusId;

  /// Flashed once in the strip; cleared on the next change.
  int? _flashId;

  CaptureCamera? _camera;
  CameraStatus _status = CameraStatus.starting;
  bool _torchOn = false;

  /// Bumped whenever the camera must be dropped (background, dispose), so
  /// an initialise that finishes late knows its result is stale.
  int _cameraGeneration = 0;
  bool _cameraStarting = false;

  /// Pages being prepared or a photo being taken.
  int _busy = 0;
  bool _submitting = false;
  ScoreUploadException? _uploadError;

  static const double _gutter = 16;
  static const double _minFrameHeight = 160;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // AC2: asked at first use, i.e. when the user reaches the camera.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _startCamera(ask: true);
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _cameraGeneration++;
    _camera?.dispose();
    _camera = null;
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    switch (state) {
      // Not `inactive`: the permission dialog makes the app inactive, and
      // dropping the camera then would re-ask in a loop.
      case AppLifecycleState.paused || AppLifecycleState.hidden:
        _stopCamera();
      case AppLifecycleState.resumed:
        // Also picks up a grant made in Settings while we were away.
        if (_camera == null && _status != CameraStatus.unavailable) {
          _startCamera(ask: false);
        }
      case AppLifecycleState.inactive || AppLifecycleState.detached:
        break;
    }
  }

  // ---------------------------------------------------------------- camera

  Future<void> _startCamera({required bool ask}) async {
    if (_cameraStarting || _camera != null) return;
    _cameraStarting = true;
    final generation = _cameraGeneration;
    final permissions = ref.read(capturePermissionsProvider);
    try {
      final PermissionOutcome outcome;
      if (ask) {
        outcome = await permissions.requestCamera();
      } else if (await permissions.cameraGranted()) {
        outcome = PermissionOutcome.granted;
      } else {
        // Leave a denied/blocked message as it is; don't re-prompt on
        // every resume.
        if (mounted && _status == CameraStatus.starting) {
          setState(() => _status = CameraStatus.denied);
        }
        return;
      }
      if (!mounted || generation != _cameraGeneration) return;
      if (outcome != PermissionOutcome.granted) {
        setState(
          () => _status = outcome == PermissionOutcome.blocked
              ? CameraStatus.blocked
              : CameraStatus.denied,
        );
        return;
      }
      setState(() => _status = CameraStatus.starting);
      final camera = ref.read(captureCameraFactoryProvider)();
      try {
        await camera.initialize();
      } on CameraUnavailableException {
        await camera.dispose();
        if (mounted && generation == _cameraGeneration) {
          setState(() => _status = CameraStatus.unavailable);
        }
        return;
      }
      if (!mounted || generation != _cameraGeneration) {
        await camera.dispose();
        return;
      }
      setState(() {
        _camera = camera;
        _status = CameraStatus.ready;
        _torchOn = false;
      });
    } finally {
      _cameraStarting = false;
    }
  }

  void _stopCamera() {
    _cameraGeneration++;
    final camera = _camera;
    if (camera == null) return;
    setState(() {
      _camera = null;
      _torchOn = false;
      if (_status == CameraStatus.ready) _status = CameraStatus.starting;
    });
    camera.dispose();
  }

  Future<void> _toggleTorch() async {
    final camera = _camera;
    if (camera == null) return;
    final on = !_torchOn;
    try {
      await camera.setTorch(on: on);
      if (mounted) setState(() => _torchOn = on);
    } catch (e) {
      debugPrint('Torch toggle failed: $e');
    }
  }

  Future<void> _openSettings() async {
    await ref.read(capturePermissionsProvider).openSettings();
  }

  // ---------------------------------------------------------- adding pages

  bool get _canAct => _busy == 0 && !_submitting;

  /// Clears the way for photos: offers to replace a PDF, refuses when full.
  Future<bool> _makeRoomForPhotos() async {
    if (_session.hasPdf) {
      final replace = await _confirm(
        title: CaptureMessages.replacePdfTitle,
        body: CaptureMessages.replacePdfWithPhotosBody,
        confirm: CaptureMessages.replace,
        cancel: CaptureMessages.keep,
      );
      if (!replace || !mounted) return false;
      _setSession(_session.withoutAll());
    }
    if (_session.photoRoom <= 0) {
      _snack(CaptureMessages.scoreFull);
      return false;
    }
    return true;
  }

  Future<void> _takePhoto() async {
    final camera = _camera;
    if (camera == null || !_canAct) return;
    if (!await _makeRoomForPhotos() || !mounted) return;
    setState(() => _busy++);
    try {
      final raw = await camera.takePicture();
      final prepared = await ref.read(pageImageProcessorProvider).prepare(raw);
      _deleteQuietly(raw);
      if (!mounted) return;
      _addPhotos([prepared], PageSource.camera);
    } on CameraUnavailableException {
      _snack(CaptureMessages.captureFailed);
    } on UnreadableImageException {
      _snack(CaptureMessages.captureFailed);
    } finally {
      if (mounted) setState(() => _busy--);
    }
  }

  Future<void> _pickGallery() async {
    if (!_canAct) return;
    if (!await _makeRoomForPhotos() || !mounted) return;
    final outcome = await ref.read(capturePermissionsProvider).requestGallery();
    if (!mounted) return;
    if (outcome != PermissionOutcome.granted) {
      await _explainGalleryDenied();
      return;
    }
    final picked = await ref.read(pagePickerProvider).pickGalleryImages();
    if (!mounted || picked.isEmpty) return;
    setState(() => _busy++);
    final prepared = <String>[];
    var unreadable = 0;
    var skipped = 0;
    try {
      final processor = ref.read(pageImageProcessorProvider);
      for (final path in picked) {
        if (prepared.length >= _session.photoRoom) {
          skipped++;
          continue;
        }
        try {
          prepared.add(await processor.prepare(path));
        } on UnreadableImageException {
          unreadable++;
        }
      }
    } finally {
      if (mounted) setState(() => _busy--);
    }
    if (!mounted) return;
    if (prepared.isNotEmpty) _addPhotos(prepared, PageSource.gallery);
    // AC7: anything that isn't a readable image never joins the score.
    if (unreadable > 0) {
      _snack(CaptureMessages.unreadablePhotos(unreadable));
    } else if (skipped > 0) {
      _snack(CaptureMessages.tooManyPhotos(prepared.length, picked.length));
    }
  }

  Future<void> _pickPdf() async {
    if (!_canAct) return;
    final PickedPdf? picked;
    try {
      picked = await ref.read(pagePickerProvider).pickPdf();
    } on NotAPdfException {
      // AC7: rejected at selection, before it can reach the upload.
      if (mounted) await _explain(CaptureMessages.notAPdf);
      return;
    }
    if (picked == null || !mounted) return;
    setState(() => _busy++);
    int pages;
    try {
      pages = await ref.read(deviceChannelProvider).pdfPageCount(picked.path);
    } on PdfUnreadableException catch (e) {
      _deleteQuietly(picked.path);
      if (mounted) {
        setState(() => _busy--);
        await _explain(CaptureMessages.pdfProblem(e.problem));
      }
      return;
    }
    if (!mounted) return;
    setState(() => _busy--);
    // AC6: checked on the phone so a long PDF never starts uploading.
    final rejection = pages <= 0
        ? CaptureMessages.pdfEmpty
        : pages > CaptureSession.maxPages
        ? CaptureMessages.pdfTooLong(pages)
        : null;
    if (rejection != null) {
      _deleteQuietly(picked.path);
      await _explain(rejection);
      return;
    }
    if (!_session.isEmpty) {
      final replace = await _confirm(
        title: _session.hasPdf
            ? CaptureMessages.replacePdfTitle
            : CaptureMessages.replacePhotosTitle(_session.pageCount),
        body: _session.hasPdf
            ? CaptureMessages.replacePdfWithPdfBody
            : CaptureMessages.replacePhotosBody,
        confirm: CaptureMessages.replace,
        cancel: CaptureMessages.keep,
      );
      if (!replace) {
        _deleteQuietly(picked.path);
        return;
      }
    }
    if (!mounted) return;
    final pdf = PdfDocument(
      id: _nextId++,
      path: picked.path,
      name: picked.name,
      pages: pages,
    );
    _setSession(_session.withPdf(pdf), flash: pdf.id);
  }

  Future<void> _showAddSheet() async {
    if (!_canAct) return;
    final choice = await showModalBottomSheet<PageSource>(
      context: context,
      showDragHandle: true,
      backgroundColor: Colors.white,
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(_gutter, 0, _gutter, 8),
              child: Semantics(
                header: true,
                child: Text(
                  CaptureMessages.addFrom,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: AppTheme.captureInk,
                  ),
                ),
              ),
            ),
            for (final (source, icon, label) in [
              if (_camera != null)
                (
                  PageSource.camera,
                  Icons.photo_camera_outlined,
                  CaptureMessages.camera,
                ),
              (
                PageSource.gallery,
                Icons.photo_library_outlined,
                CaptureMessages.gallery,
              ),
              (
                PageSource.pdf,
                Icons.picture_as_pdf_outlined,
                CaptureMessages.pdf,
              ),
            ])
              ListTile(
                leading: Icon(icon, color: AppTheme.captureInk),
                title: Text(
                  label,
                  style: const TextStyle(color: AppTheme.captureInk),
                ),
                onTap: () => Navigator.of(context).pop(source),
              ),
          ],
        ),
      ),
    );
    if (!mounted) return;
    switch (choice) {
      case PageSource.camera:
        await _takePhoto();
      case PageSource.gallery:
        await _pickGallery();
      case PageSource.pdf:
        await _pickPdf();
      case null:
        break;
    }
  }

  void _addPhotos(List<String> paths, PageSource source) {
    final photos = [
      for (final path in paths)
        PhotoPage(id: _nextId++, path: path, source: source),
    ];
    final next = _session.addPhotos(photos);
    final added = next.items.length - _session.items.length;
    _setSession(next, flash: added > 0 ? photos[added - 1].id : null);
  }

  void _setSession(CaptureSession next, {int? flash, int? focus}) {
    setState(() {
      _session = next;
      _flashId = flash;
      _uploadError = null;
      final keep = focus ?? flash ?? _focusId;
      _focusId = keep != null && next.indexOf(keep) >= 0
          ? keep
          : (next.isEmpty ? null : next.items.last.id);
    });
  }

  // ----------------------------------------------------- strip interactions

  void _reorder(int oldIndex, int newIndex) {
    final id = _session.items[oldIndex].id;
    _setSession(_session.reorder(oldIndex, newIndex), focus: id);
    final index = _session.indexOf(id) + 1;
    SemanticsService.sendAnnouncement(
      View.of(context),
      CaptureMessages.pageOf(index, _session.pageCount),
      Directionality.of(context),
    );
  }

  void _remove(CaptureItem item) {
    final index = _session.indexOf(item.id);
    if (index < 0) return;
    _setSession(_session.remove(item.id));
    final messenger = ScaffoldMessenger.of(context)..hideCurrentSnackBar();
    messenger.showSnackBar(
      SnackBar(
        content: Text(
          item is PdfDocument
              ? CaptureMessages.pdfRemoved
              : CaptureMessages.removed(index + 1),
        ),
        action: SnackBarAction(
          label: CaptureMessages.undo,
          onPressed: () => _undoRemove(index, item),
        ),
      ),
    );
  }

  void _undoRemove(int index, CaptureItem item) {
    if (!mounted) return;
    // The strip may have changed since: never let Undo mix a PDF with
    // photos or push a score past the page limit.
    final fits = switch (item) {
      PdfDocument() => _session.isEmpty,
      PhotoPage() => !_session.hasPdf && _session.photoRoom > 0,
    };
    if (!fits || _session.indexOf(item.id) >= 0) return;
    _setSession(_session.insert(index, item), flash: item.id);
  }

  Future<void> _edit(PhotoPage page) async {
    if (!_canAct) return;
    final newPath = await Navigator.of(context).push<String>(
      MaterialPageRoute(builder: (_) => EditPageScreen(path: page.path)),
    );
    if (newPath == null || !mounted) return;
    _setSession(_session.replacePath(page.id, newPath), flash: page.id);
  }

  Future<void> _open(CaptureItem item) {
    final index = _session.indexOf(item.id);
    return Navigator.of(context).push<void>(
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => PagePreviewScreen(
          item: item,
          number: index + 1,
          total: _session.pageCount,
        ),
      ),
    );
  }

  // ------------------------------------------------------- leave and submit

  Future<void> _close() async {
    if (_submitting) return;
    if (_session.isEmpty) {
      Navigator.of(context).pop();
      return;
    }
    final discard = await _confirm(
      title: CaptureMessages.discardTitle(_session.pageCount),
      body: CaptureMessages.discardBody,
      confirm: CaptureMessages.discard,
      cancel: CaptureMessages.keepEditing,
    );
    if (discard && mounted) Navigator.of(context).pop();
  }

  Future<void> _submit() async {
    if (_submitting || _session.isEmpty || _busy > 0) return;
    setState(() {
      _submitting = true;
      _uploadError = null;
    });
    final api = ref.read(scoreUploadApiProvider);
    try {
      // AC8: a PDF goes to PIYA-310, camera/gallery photos to PIYA-101.
      final pdf = _session.pdf;
      final job = pdf != null
          ? await api.submitPdf(details: widget.details, pdfPath: pdf.path)
          : await api.submitImages(
              details: widget.details,
              imagePaths: [for (final page in _session.photos) page.path],
            );
      if (!mounted) return;
      ref.invalidate(scoreLibraryProvider);
      // Details and Capture leave the stack: Back from Processing returns
      // to the library, not to a form that was already sent.
      Navigator.of(context).pushNamedAndRemoveUntil(
        AppRoutes.processing,
        (route) =>
            route.settings.name == AppRoutes.scoreLibrary || route.isFirst,
        arguments: ProcessingArguments(
          jobId: job.jobId,
          title: widget.details.title,
        ),
      );
    } on ScoreUploadException catch (e) {
      if (mounted) {
        setState(() {
          _submitting = false;
          _uploadError = e;
        });
      }
    }
  }

  Future<void> _returnToLogin() async {
    try {
      await ref.read(sessionStorageProvider).clear();
    } catch (e) {
      // The server already rejected the token; failing to wipe it locally
      // must not trap the user here.
      debugPrint('Session clear failed: $e');
    }
    if (!mounted) return;
    Navigator.of(context)
        .pushNamedAndRemoveUntil(AppRoutes.login, (_) => false);
  }

  // ---------------------------------------------------------------- helpers

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _explain(String body) => showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      content: Text(body),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('OK'),
        ),
      ],
    ),
  );

  Future<bool> _confirm({
    required String title,
    required String body,
    required String confirm,
    required String cancel,
  }) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(body),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(cancel),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(confirm),
          ),
        ],
      ),
    );
    return result ?? false;
  }

  Future<void> _explainGalleryDenied() async {
    final open = await _confirm(
      title: CaptureMessages.photosNeededTitle,
      body: CaptureMessages.photosNeededBody,
      confirm: CaptureMessages.openSettings,
      cancel: CaptureMessages.notNow,
    );
    if (open) await _openSettings();
  }

  void _deleteQuietly(String path) {
    File(path).delete().ignore();
  }

  // ------------------------------------------------------------------ build

  @override
  Widget build(BuildContext context) {
    final count = _session.pageCount;
    return PopScope(
      canPop: _session.isEmpty && !_submitting,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _close();
      },
      child: Scaffold(
        body: DecoratedBox(
          decoration: const BoxDecoration(
            gradient: AppTheme.captureBackgroundGradient,
          ),
          child: SafeArea(
            child: CustomScrollView(
              slivers: [
                SliverFillRemaining(
                  hasScrollBody: false,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(_gutter, 8, _gutter, 12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _TopBar(
                          onClose: _submitting ? null : _close,
                          torchOn: _torchOn,
                          onTorch: _camera == null ? null : _toggleTorch,
                        ),
                        const SizedBox(height: 12),
                        Expanded(
                          child: _MinIntrinsicHeight(
                            height: _minFrameHeight,
                            child: CameraFrame(
                              status: _status,
                              camera: _camera,
                              onAllowCamera: () => _startCamera(ask: true),
                              onOpenSettings: _openSettings,
                              overlay: _busy > 0 ? const _BusyOverlay() : null,
                            ),
                          ),
                        ),
                        const SizedBox(height: 12),
                        _InputRow(
                          onGallery: _canAct ? _pickGallery : null,
                          onShutter: _camera != null && _canAct
                              ? _takePhoto
                              : null,
                          onPdf: _canAct ? _pickPdf : null,
                        ),
                        const SizedBox(height: 12),
                        _StripHeading(session: _session, focusId: _focusId),
                        const SizedBox(height: 4),
                        PageStrip(
                          items: _session.items,
                          imageSource: ref.read(pageImageSourceProvider),
                          flashId: _flashId,
                          enabled: _canAct,
                          onReorder: _reorder,
                          onOpen: _open,
                          onEdit: _edit,
                          onRemove: _remove,
                          onAdd: _session.hasPdf ? null : _showAddSheet,
                        ),
                        if (_uploadError case final error?) ...[
                          const SizedBox(height: 8),
                          _UploadErrorBanner(
                            message: CaptureMessages.uploadError(error),
                            onLogIn: error is UploadSessionExpiredException
                                ? _returnToLogin
                                : null,
                          ),
                        ],
                        const SizedBox(height: 12),
                        PrimaryPillButton(
                          label: count == 0
                              ? CaptureMessages.createScore
                              : CaptureMessages.createScoreWith(count),
                          onPressed: count == 0 || _busy > 0 ? null : _submit,
                          isLoading: _submitting,
                          backgroundColor: AppTheme.captureAccent,
                          foregroundColor: AppTheme.captureInk,
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Reports a fixed minimum height to intrinsic queries. SliverFillRemaining
/// asks its child for an intrinsic height to decide when to scroll, and the
/// camera frame (a LayoutBuilder) can't answer; this lets the frame shrink
/// to [height] on short screens and makes the page scroll below that.
class _MinIntrinsicHeight extends SingleChildRenderObjectWidget {
  const _MinIntrinsicHeight({required this.height, super.child});

  final double height;

  @override
  RenderObject createRenderObject(BuildContext context) =>
      _RenderMinIntrinsicHeight(height);

  @override
  void updateRenderObject(
    BuildContext context,
    _RenderMinIntrinsicHeight renderObject,
  ) {
    renderObject.height = height;
  }
}

class _RenderMinIntrinsicHeight extends RenderProxyBox {
  _RenderMinIntrinsicHeight(this._height);

  double _height;
  set height(double value) {
    if (value == _height) return;
    _height = value;
    markNeedsLayout();
  }

  @override
  double computeMinIntrinsicHeight(double width) => _height;

  @override
  double computeMaxIntrinsicHeight(double width) => _height;

  @override
  double computeMinIntrinsicWidth(double height) => 0;

  @override
  double computeMaxIntrinsicWidth(double height) => 0;
}

class _TopBar extends StatelessWidget {
  const _TopBar({
    required this.onClose,
    required this.torchOn,
    required this.onTorch,
  });

  final VoidCallback? onClose;
  final bool torchOn;
  final VoidCallback? onTorch;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        IconButton.filled(
          tooltip: CaptureMessages.close,
          onPressed: onClose,
          style: IconButton.styleFrom(
            backgroundColor: AppTheme.captureCloseFill,
            foregroundColor: Colors.white,
            minimumSize: const Size(48, 48),
          ),
          icon: const Icon(Icons.close_rounded),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Semantics(
            header: true,
            child: Text(
              CaptureMessages.alignInFrame,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                color: AppTheme.captureInk,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ),
        const SizedBox(width: 8),
        // Kept in the layout when hidden so the title stays centred.
        Visibility.maintain(
          visible: onTorch != null,
          child: IconButton(
            tooltip: torchOn
                ? CaptureMessages.flashOff
                : CaptureMessages.flashOn,
            isSelected: torchOn,
            onPressed: onTorch,
            style: IconButton.styleFrom(
              foregroundColor: AppTheme.captureInk,
              minimumSize: const Size(48, 48),
            ),
            icon: Icon(
              torchOn ? Icons.flash_on_rounded : Icons.flash_off_rounded,
            ),
          ),
        ),
      ],
    );
  }
}

class _BusyOverlay extends StatelessWidget {
  const _BusyOverlay();

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: AppTheme.captureInk.withValues(alpha: 0.7),
      child: Center(
        child: Semantics(
          liveRegion: true,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const CircularProgressIndicator(color: AppTheme.captureAccent),
              const SizedBox(height: 12),
              Text(
                CaptureMessages.preparingPage,
                style: Theme.of(context).textTheme.bodyMedium
                    ?.copyWith(color: Colors.white),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _InputRow extends StatelessWidget {
  const _InputRow({
    required this.onGallery,
    required this.onShutter,
    required this.onPdf,
  });

  final VoidCallback? onGallery;
  final VoidCallback? onShutter;
  final VoidCallback? onPdf;

  static const double _shutterSize = 72;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: _LabelledInput(
            icon: Icons.photo_library_outlined,
            label: CaptureMessages.gallery,
            onTap: onGallery,
          ),
        ),
        Semantics(
          button: true,
          enabled: onShutter != null,
          label: CaptureMessages.shutter,
          excludeSemantics: true,
          onTap: onShutter,
          child: Opacity(
            opacity: onShutter == null ? 0.4 : 1,
            child: Material(
              shape: const CircleBorder(
                side: BorderSide(color: AppTheme.captureInk, width: 4),
              ),
              color: Colors.white,
              child: InkWell(
                customBorder: const CircleBorder(),
                onTap: onShutter,
                child: const SizedBox.square(
                  dimension: _shutterSize,
                  child: Icon(
                    Icons.photo_camera_rounded,
                    size: 32,
                    color: AppTheme.captureInk,
                  ),
                ),
              ),
            ),
          ),
        ),
        Expanded(
          child: _LabelledInput(
            icon: Icons.picture_as_pdf_outlined,
            label: CaptureMessages.pdf,
            onTap: onPdf,
          ),
        ),
      ],
    );
  }
}

class _LabelledInput extends StatelessWidget {
  const _LabelledInput({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      enabled: onTap != null,
      label: label,
      excludeSemantics: true,
      onTap: onTap,
      child: Opacity(
        opacity: onTap == null ? 0.5 : 1,
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: onTap,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 48, minWidth: 48),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 48,
                    height: 48,
                    decoration: const BoxDecoration(
                      color: AppTheme.captureInk,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(icon, color: AppTheme.captureAccent),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    label,
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.labelLarge?.copyWith(
                      color: AppTheme.captureInk,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _StripHeading extends StatelessWidget {
  const _StripHeading({required this.session, required this.focusId});

  final CaptureSession session;
  final int? focusId;

  @override
  Widget build(BuildContext context) {
    final pdf = session.pdf;
    final String text;
    if (session.isEmpty) {
      text = CaptureMessages.noPagesYet;
    } else if (pdf != null) {
      text = CaptureMessages.pdfCard(pdf.pages);
    } else {
      final index = focusId == null ? -1 : session.indexOf(focusId!);
      text = CaptureMessages.pageOf(
        index < 0 ? session.pageCount : index + 1,
        session.pageCount,
      );
    }
    return Semantics(
      liveRegion: true,
      child: Text(
        text,
        style: Theme.of(context).textTheme.labelLarge
            ?.copyWith(color: AppTheme.captureInk, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _UploadErrorBanner extends StatelessWidget {
  const _UploadErrorBanner({required this.message, required this.onLogIn});

  final String message;
  final VoidCallback? onLogIn;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      container: true,
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 10, 8, 10),
        decoration: BoxDecoration(
          color: AppTheme.errorBannerFill,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          children: [
            const Icon(Icons.error_outline_rounded, color: AppTheme.errorRed),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                message,
                style: Theme.of(context).textTheme.bodyMedium
                    ?.copyWith(color: AppTheme.errorRed),
              ),
            ),
            if (onLogIn != null)
              TextButton(
                onPressed: onLogIn,
                style: TextButton.styleFrom(
                  foregroundColor: AppTheme.errorRed,
                  minimumSize: const Size(48, 48),
                ),
                child: const Text(CaptureMessages.logIn),
              ),
          ],
        ),
      ),
    );
  }
}
