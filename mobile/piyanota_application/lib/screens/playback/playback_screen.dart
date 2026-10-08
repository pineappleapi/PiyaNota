import 'dart:async';

import 'package:clock/clock.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/score_result.dart';
import '../../models/score_timeline.dart';
import '../../models/voice_part.dart';
import '../../routes/app_routes.dart';
import '../../state/playback_providers.dart';
import '../../state/session_actions.dart';
import '../../theme/app_theme.dart';
import '../../widgets/primary_pill_button.dart';
import 'playback_messages.dart';

/// Score Playback & Rehearsal (PIYA-208): the original page image with an
/// indicator band that follows the audio, S/A/T/B chips, and the transport.
class PlaybackScreen extends ConsumerStatefulWidget {
  const PlaybackScreen({super.key, required this.scoreId, required this.title});

  final int scoreId;
  final String title;

  @override
  ConsumerState<PlaybackScreen> createState() => _PlaybackScreenState();
}

class _PlaybackScreenState extends ConsumerState<PlaybackScreen>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver {
  /// What the seek bar, times and band show. Follows the engine's audio
  /// position every frame while playing, and the finger while dragging
  /// (AC7), so the band moves on the next frame, not after the seek lands.
  final ValueNotifier<Duration> _display = ValueNotifier(Duration.zero);

  /// Bumped on every seek the user asks for, so the score view scrolls the
  /// band into view even if they scrolled away moments before.
  final ValueNotifier<int> _jumps = ValueNotifier(0);
  late final Ticker _ticker = createTicker((_) => _syncDisplay());
  bool _dragging = false;
  bool _leaving = false;

  PlaybackController get _controller =>
      ref.read(playbackControllerProvider(widget.scoreId).notifier);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _ticker.dispose();
    _display.dispose();
    _jumps.dispose();
    super.dispose();
  }

  /// Backgrounding pauses (the engine itself is released when the screen's
  /// provider is disposed on leaving).
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.hidden) {
      _run(_controller.pause(), 'pause on background');
    }
  }

  void _syncDisplay() {
    if (!_dragging) _display.value = _controller.position;
  }

  /// Fire-and-forget for transport calls: a throw is logged, never left
  /// unhandled. Engine failures reach the screen as the audio error state
  /// through the controller, not through these futures.
  void _run(Future<void> call, String what) {
    unawaited(
      call.catchError((Object e, StackTrace stack) {
        debugPrint('Playback: $what failed: $e\n$stack');
      }),
    );
  }

  Future<void> _afterSeek(Future<void> seek) async {
    try {
      await seek;
    } on Object catch (e, stack) {
      debugPrint('Playback: seek failed: $e\n$stack');
    }
    if (!mounted) return;
    _syncDisplay();
    _jumps.value++;
  }

  /// AC7: the display already shows [value]; a failed seek must still let
  /// the seek bar, times and band follow the audio again.
  Future<void> _onSeekEnd(Duration value) async {
    _display.value = value;
    try {
      await _controller.seek(value);
    } on Object catch (e, stack) {
      debugPrint('Playback: seek failed: $e\n$stack');
    } finally {
      _dragging = false;
      if (mounted) {
        _syncDisplay();
        _jumps.value++;
      }
    }
  }

  void _onPlayingChanged(bool playing) {
    if (playing) {
      if (!_ticker.isActive) unawaited(_ticker.start());
    } else {
      if (_ticker.isActive) _ticker.stop();
      _syncDisplay();
    }
  }

  Future<void> _back() async {
    if (_leaving) return;
    _leaving = true;
    try {
      await _controller.pause();
    } on Object catch (e, stack) {
      // Leaving disposes the engine anyway, which stops the audio.
      debugPrint('Playback: pause on leaving failed: $e\n$stack');
    }
    if (!mounted) return;
    final navigator = Navigator.of(context);
    if (navigator.canPop()) {
      navigator.pop();
    } else {
      await navigator.pushReplacementNamed(AppRoutes.scoreLibrary);
    }
  }

  Future<void> _toLogin() async {
    if (_leaving) return;
    _leaving = true;
    await endLocalSession(ref);
    if (!mounted) return;
    await Navigator.of(context)
        .pushNamedAndRemoveUntil(AppRoutes.login, (_) => false);
  }

  void _toggleVoice(VoicePart voice) {
    if (_controller.toggleVoice(voice)) return;
    final state = ref.read(playbackControllerProvider(widget.scoreId));
    if (state.selected.length == 1 && state.selected.contains(voice)) {
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(
          const SnackBar(content: Text(PlaybackMessages.keepOneVoice)),
        );
    }
  }

  /// PIYA-209/210/211 land later. A modal sheet, not a route push, so the
  /// music keeps playing underneath (user decision 2026-10-09).
  void _openPlaceholder(String title) {
    unawaited(
      showModalBottomSheet<void>(
        context: context,
        backgroundColor: Colors.white,
        builder: (_) => _ComingSoonSheet(title: title),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = playbackControllerProvider(widget.scoreId);
    ref.listen(provider.select((s) => s.playing), (_, playing) {
      _onPlayingChanged(playing);
    });
    ref.listen(provider.select((s) => s.error), (_, error) {
      if (error == PlaybackError.sessionExpired) unawaited(_toLogin());
    });
    final state = ref.watch(provider);
    final ready = state.phase == PlaybackPhase.ready;
    final error = state.error ?? PlaybackError.server;

    final Widget body = switch (state.phase) {
      PlaybackPhase.loading => const _LoadingView(),
      PlaybackPhase.failed when state.error == PlaybackError.sessionExpired =>
        const _LoadingView(),
      PlaybackPhase.failed => _ErrorView(
        error: error,
        onRetry: error == PlaybackError.notFound
            ? null
            : () => _run(_controller.retry(), 'retry'),
        onBack: () => unawaited(_back()),
      ),
      PlaybackPhase.ready => Stack(
        children: [
          Positioned.fill(
            child: _ScoreView(
              result: state.result!,
              timeline: state.timeline ?? ScoreTimeline.empty,
              display: _display,
              jumps: _jumps,
            ),
          ),
          if (state.showReviewBanner)
            Positioned(
              top: 8,
              left: 12,
              right: 12,
              child: _ReviewBanner(onDismiss: _controller.dismissReview),
            ),
        ],
      ),
    };

    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) unawaited(_back());
      },
      child: Scaffold(
        backgroundColor: Colors.white,
        body: SafeArea(
          bottom: !ready,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _Header(
                title: widget.title,
                composer: state.composer,
                onBack: () => unawaited(_back()),
                onDownload: ready
                    ? () => _openPlaceholder(PlaybackMessages.exportSheetTitle)
                    : null,
              ),
              if (ready)
                _VoiceChips(
                  available: state.available,
                  selected: state.selected,
                  onToggle: _toggleVoice,
                ),
              if (ready && state.timingUnavailable)
                const _IndicatorUnavailableNote(),
              Expanded(child: body),
            ],
          ),
        ),
        bottomNavigationBar: ready
            ? _ControlPanel(
                display: _display,
                duration: state.duration,
                playing: state.playing,
                onPlayPause: () => _run(_controller.togglePlay(), 'play'),
                onToStart: () =>
                    unawaited(_afterSeek(_controller.skipToStart())),
                onToEnd: () => unawaited(_afterSeek(_controller.skipToEnd())),
                onBack5: () => unawaited(
                  _afterSeek(_controller.skipBy(-PlaybackController.skipStep)),
                ),
                onForward5: () => unawaited(
                  _afterSeek(_controller.skipBy(PlaybackController.skipStep)),
                ),
                onSeekChanged: (value) {
                  _dragging = true;
                  _display.value = value;
                },
                onSeekEnd: (value) => unawaited(_onSeekEnd(value)),
                onMixer: () =>
                    _openPlaceholder(PlaybackMessages.mixerSheetTitle),
                onSpeed: () =>
                    _openPlaceholder(PlaybackMessages.speedSheetTitle),
              )
            : null,
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({
    required this.title,
    required this.composer,
    required this.onBack,
    required this.onDownload,
  });

  final String title;
  final String? composer;
  final VoidCallback onBack;
  final VoidCallback? onDownload;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _NavyDisc(
            icon: Icons.arrow_back_rounded,
            tooltip: PlaybackMessages.back,
            onPressed: onBack,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: MediaQuery.withClampedTextScaling(
              maxScaleFactor: 1.3,
              child: Column(
                children: [
                  Semantics(
                    header: true,
                    child: Text(
                      title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      textAlign: TextAlign.center,
                      style: textTheme.titleLarge?.copyWith(
                        fontSize: 22,
                        height: 1.15,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.playbackTitle,
                      ),
                    ),
                  ),
                  if (composer case final composer?) ...[
                    const SizedBox(height: 2),
                    Text(
                      PlaybackMessages.arrangedBy(composer),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      textAlign: TextAlign.center,
                      style: textTheme.bodyMedium?.copyWith(
                        color: AppTheme.playbackSubtle,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(width: 8),
          // Kept in the layout while loading so the title stays centred.
          Visibility.maintain(
            visible: onDownload != null,
            child: _NavyDisc(
              icon: Icons.download_rounded,
              tooltip: PlaybackMessages.download,
              onPressed: onDownload,
            ),
          ),
        ],
      ),
    );
  }
}

class _NavyDisc extends StatelessWidget {
  const _NavyDisc({
    required this.icon,
    required this.tooltip,
    required this.onPressed,
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback? onPressed;

  /// The mockup's disc; the padded tap target makes it 48.
  static const double _size = 44;

  @override
  Widget build(BuildContext context) {
    return IconButton.filled(
      tooltip: tooltip,
      onPressed: onPressed,
      icon: Icon(icon),
      iconSize: 26,
      style: IconButton.styleFrom(
        backgroundColor: AppTheme.playbackNavy,
        foregroundColor: Colors.white,
        disabledBackgroundColor: AppTheme.playbackNavy,
        disabledForegroundColor: Colors.white,
        fixedSize: const Size.square(_size),
        minimumSize: const Size.square(_size),
        padding: EdgeInsets.zero,
        tapTargetSize: MaterialTapTargetSize.padded,
      ),
    );
  }
}

class _VoiceChips extends StatelessWidget {
  const _VoiceChips({
    required this.available,
    required this.selected,
    required this.onToggle,
  });

  final Set<VoicePart> available;
  final Set<VoicePart> selected;
  final ValueChanged<VoicePart> onToggle;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return MediaQuery.withClampedTextScaling(
      maxScaleFactor: 1.3,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              PlaybackMessages.selectVoices,
              style: textTheme.bodyMedium?.copyWith(
                color: AppTheme.playbackSubtle,
              ),
            ),
            Wrap(
              spacing: 8,
              children: [
                for (final voice in VoicePart.values)
                  _VoiceChip(
                    voice: voice,
                    available: available.contains(voice),
                    selected: selected.contains(voice),
                    onToggle: onToggle,
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _VoiceChip extends StatelessWidget {
  const _VoiceChip({
    required this.voice,
    required this.available,
    required this.selected,
    required this.onToggle,
  });

  final VoicePart voice;
  final bool available;
  final bool selected;
  final ValueChanged<VoicePart> onToggle;

  static const double _unavailableAlpha = 0.45;

  @override
  Widget build(BuildContext context) {
    final on = selected && available;
    final chip = FilterChip(
      key: ValueKey('voice-chip-${voice.name}'),
      label: Text(PlaybackMessages.voiceChip(voice)),
      selected: on,
      onSelected: available ? (_) => onToggle(voice) : null,
      showCheckmark: true,
      checkmarkColor: Colors.white,
      selectedColor: AppTheme.playbackChipSelectedFill,
      backgroundColor: AppTheme.playbackChipFill,
      disabledColor: AppTheme.playbackChipFill.withValues(
        alpha: _unavailableAlpha,
      ),
      labelStyle: TextStyle(
        fontWeight: FontWeight.w600,
        color: on
            ? Colors.white
            : available
            ? AppTheme.playbackChipText
            : AppTheme.playbackChipText.withValues(alpha: _unavailableAlpha),
        decoration: available ? null : TextDecoration.lineThrough,
      ),
      shape: const StadiumBorder(),
      side: BorderSide.none,
      materialTapTargetSize: MaterialTapTargetSize.padded,
    );
    return available
        ? chip
        : Semantics(hint: PlaybackMessages.voiceUnavailable, child: chip);
  }
}

class _LoadingView extends StatelessWidget {
  const _LoadingView();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Semantics(
        liveRegion: true,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const CircularProgressIndicator(color: AppTheme.playbackNavy),
            const SizedBox(height: 16),
            Text(
              PlaybackMessages.loading,
              style: Theme.of(context).textTheme.bodyLarge
                  ?.copyWith(color: AppTheme.playbackSubtle),
            ),
          ],
        ),
      ),
    );
  }
}

/// FR-14: one view per failure kind, each with its own heading, icon and
/// copy, so "still converting" never reads like "no internet".
/// The timing file didn't load: the audio plays, the band can't. Said
/// once, quietly, so the missing band doesn't look like a bug.
class _IndicatorUnavailableNote extends StatelessWidget {
  const _IndicatorUnavailableNote();

  @override
  Widget build(BuildContext context) {
    return Padding(
      key: const ValueKey('indicator-unavailable'),
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
      child: Text(
        PlaybackMessages.indicatorUnavailable,
        textAlign: TextAlign.center,
        style: Theme.of(context).textTheme.bodySmall
            ?.copyWith(color: AppTheme.playbackSubtle),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({
    required this.error,
    required this.onRetry,
    required this.onBack,
  });

  final PlaybackError error;

  /// Null hides Retry: a score that is gone (404) won't come back by
  /// asking again, so the only way on is back to the library.
  final VoidCallback? onRetry;
  final VoidCallback onBack;

  static const double _iconSize = 48;

  IconData get _icon => switch (error) {
    PlaybackError.notReady => Icons.hourglass_top_rounded,
    PlaybackError.notFound => Icons.search_off_rounded,
    PlaybackError.network => Icons.wifi_off_rounded,
    PlaybackError.audio => Icons.music_off_rounded,
    PlaybackError.server ||
    PlaybackError.sessionExpired => Icons.error_outline_rounded,
  };

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(24, 32, 24, 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Icon(_icon, size: _iconSize, color: AppTheme.playbackNavy),
          const SizedBox(height: 12),
          Semantics(
            header: true,
            child: Text(
              PlaybackMessages.errorHeading(error),
              textAlign: TextAlign.center,
              style: textTheme.headlineSmall?.copyWith(
                fontSize: 22,
                fontWeight: FontWeight.w700,
                color: AppTheme.playbackTitle,
              ),
            ),
          ),
          const SizedBox(height: 8),
          Semantics(
            liveRegion: true,
            child: Text(
              PlaybackMessages.errorBody(error),
              textAlign: TextAlign.center,
              style: textTheme.bodyLarge?.copyWith(
                color: AppTheme.onboardingBody,
              ),
            ),
          ),
          const SizedBox(height: 24),
          if (onRetry case final retry?) ...[
            PrimaryPillButton(
              label: PlaybackMessages.retry,
              onPressed: retry,
              backgroundColor: AppTheme.processingSecondary,
            ),
            const SizedBox(height: 8),
          ],
          OutlinedButton(
            onPressed: onBack,
            style: OutlinedButton.styleFrom(
              foregroundColor: AppTheme.processingSecondary,
              side: const BorderSide(color: AppTheme.processingSecondary),
              minimumSize: const Size.fromHeight(48),
              shape: const StadiumBorder(),
            ),
            child: const Text(PlaybackMessages.backToLibrary),
          ),
        ],
      ),
    );
  }
}

class _ReviewBanner extends StatelessWidget {
  const _ReviewBanner({required this.onDismiss});

  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    return Material(
      key: const ValueKey('review-banner'),
      color: AppTheme.playbackReviewFill,
      elevation: 2,
      borderRadius: BorderRadius.circular(12),
      child: Padding(
        padding: const EdgeInsets.only(left: 12),
        child: Row(
          children: [
            const Icon(
              Icons.info_outline_rounded,
              size: 20,
              color: AppTheme.playbackReviewText,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Semantics(
                liveRegion: true,
                child: Text(
                  PlaybackMessages.review,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    fontSize: 13,
                    color: AppTheme.playbackReviewText,
                  ),
                ),
              ),
            ),
            IconButton(
              tooltip: PlaybackMessages.dismissReview,
              onPressed: onDismiss,
              color: AppTheme.playbackReviewText,
              icon: const Icon(Icons.close_rounded, size: 20),
            ),
          ],
        ),
      ),
    );
  }
}

/// The original page images, fit to width and stacked vertically (FR-8,
/// AC1), with the indicator band drawn over the page it is on (AC6).
class _ScoreView extends StatefulWidget {
  const _ScoreView({
    required this.result,
    required this.timeline,
    required this.display,
    required this.jumps,
  });

  final ScoreResult result;
  final ScoreTimeline timeline;
  final ValueListenable<Duration> display;
  final Listenable jumps;

  @override
  State<_ScoreView> createState() => _ScoreViewState();
}

class _ScoreViewState extends State<_ScoreView> {
  /// The band's width at the mockup's 412 dp screen width; scales with
  /// the page.
  static const double _bandWidth = 18;
  static const double _referenceWidth = 412;
  static const double _gutter = 12;
  static const double _pageGap = 12;

  /// A page whose size isn't known yet is laid out as A4 portrait.
  static const double _fallbackAspect = 1.414;

  /// Hands-off time after the user scrolls the score themselves.
  static const Duration _manualScrollGrace = Duration(seconds: 3);
  static const Duration _scrollDuration = Duration(milliseconds: 350);

  /// Where the band's top lands when the view scrolls to it.
  static const double _followAnchor = 0.08;

  final ScrollController _scroll = ScrollController();
  final Map<int, Size> _decoded = {};
  final List<(ImageStream, ImageStreamListener)> _streams = [];
  DateTime? _lastUserScroll;
  bool _autoScrolling = false;
  int _scrollAnimation = 0;
  double _pageWidth = 0;

  @override
  void initState() {
    super.initState();
    widget.display.addListener(_follow);
    widget.jumps.addListener(_onJump);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _resolveSizes();
  }

  @override
  void dispose() {
    widget.display.removeListener(_follow);
    widget.jumps.removeListener(_onJump);
    for (final (stream, listener) in _streams) {
      stream.removeListener(listener);
    }
    _scroll.dispose();
    super.dispose();
  }

  static ImageProvider? _imageFor(Uri uri) => switch (uri.scheme) {
    'asset' => AssetImage(uri.path.substring(1)),
    'http' || 'https' => NetworkImage(uri.toString()),
    _ => null,
  };

  /// Pages without a server-given size are measured from the decoded
  /// image (see ScoreResult.pageSizes).
  void _resolveSizes() {
    if (_streams.isNotEmpty) return;
    final images = widget.result.scoreImages;
    for (var i = 0; i < images.length; i++) {
      if (widget.result.pageSizeAt(i) != null) continue;
      final provider = _imageFor(images[i]);
      if (provider == null) continue;
      final stream = provider.resolve(createLocalImageConfiguration(context));
      final listener = ImageStreamListener(
        (info, _) {
          if (!mounted) return;
          setState(() {
            _decoded[i] = Size(
              info.image.width.toDouble(),
              info.image.height.toDouble(),
            );
          });
        },
        onError: (error, _) {
          // The page still shows (at A4 proportions); only the band's
          // placement on it may be off.
          debugPrint('Playback: page ${i + 1} size unreadable: $error');
        },
      );
      stream.addListener(listener);
      _streams.add((stream, listener));
    }
  }

  Size? _naturalSize(int page) =>
      widget.result.pageSizeAt(page) ?? _decoded[page];

  double _pageHeight(int page) {
    final size = _naturalSize(page);
    return size == null
        ? _pageWidth * _fallbackAspect
        : _pageWidth * size.height / size.width;
  }

  double _scaleFor(int page) {
    final size = _naturalSize(page);
    return size == null ? 0 : _pageWidth / size.width;
  }

  double _pageTop(int page) {
    var top = 0.0;
    for (var i = 0; i < page; i++) {
      top += _pageHeight(i) + _pageGap;
    }
    return top;
  }

  /// A seek the user asked for wins over a follow animation still running
  /// (it would otherwise land on the old spot and ignore the jump).
  void _onJump() {
    _lastUserScroll = null;
    _follow(interrupt: true);
  }

  /// Keeps the band on screen while it moves, unless the user scrolled in
  /// the last few seconds (don't fight them).
  void _follow({bool interrupt = false}) {
    if (!_scroll.hasClients || _pageWidth <= 0) return;
    if (_autoScrolling && !interrupt) return;
    final position = widget.timeline.positionAt(widget.display.value);
    if (position == null) return;
    if (position.pageIndex >= widget.result.scoreImages.length) return;
    final scale = _scaleFor(position.pageIndex);
    if (scale == 0) return;
    final userScrolled = _lastUserScroll;
    if (userScrolled != null &&
        clock.now().difference(userScrolled) < _manualScrollGrace) {
      return;
    }
    final pageTop = _pageTop(position.pageIndex);
    final top = pageTop + position.top * scale;
    final bottom = pageTop + position.bottom * scale;
    final metrics = _scroll.position;
    final viewTop = metrics.pixels;
    final viewBottom = viewTop + metrics.viewportDimension;
    if (top >= viewTop && bottom <= viewBottom) return;
    final target = (top - metrics.viewportDimension * _followAnchor).clamp(
      metrics.minScrollExtent,
      metrics.maxScrollExtent,
    );
    _autoScrolling = true;
    final animation = ++_scrollAnimation;
    unawaited(
      _scroll
          .animateTo(target, duration: _scrollDuration, curve: Curves.easeInOut)
          .whenComplete(() {
            // An interrupted animation completes too; only the newest one
            // may clear the flag.
            if (animation == _scrollAnimation) _autoScrolling = false;
          }),
    );
  }

  bool _onScroll(ScrollNotification notification) {
    if (notification is ScrollStartNotification &&
        notification.dragDetails != null) {
      _lastUserScroll = clock.now();
    } else if (notification is ScrollUpdateNotification &&
        notification.dragDetails != null) {
      _lastUserScroll = clock.now();
    }
    return false;
  }

  @override
  Widget build(BuildContext context) {
    final images = widget.result.scoreImages;
    if (images.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            PlaybackMessages.noScoreImage,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodyLarge
                ?.copyWith(color: AppTheme.playbackSubtle),
          ),
        ),
      );
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        _pageWidth = constraints.maxWidth - 2 * _gutter;
        final bandWidth =
            _bandWidth * MediaQuery.sizeOf(context).width / _referenceWidth;
        return NotificationListener<ScrollNotification>(
          onNotification: _onScroll,
          child: SingleChildScrollView(
            key: const ValueKey('score-scroll'),
            controller: _scroll,
            padding: const EdgeInsets.fromLTRB(_gutter, 8, _gutter, 16),
            child: Column(
              children: [
                for (var i = 0; i < images.length; i++) ...[
                  if (i > 0) const SizedBox(height: _pageGap),
                  _ScorePage(
                    pageIndex: i,
                    pageCount: images.length,
                    image: _imageFor(images[i]),
                    width: _pageWidth,
                    height: _pageHeight(i),
                    scale: _scaleFor(i),
                    bandWidth: bandWidth,
                    timeline: widget.timeline,
                    display: widget.display,
                  ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }
}

class _ScorePage extends StatelessWidget {
  const _ScorePage({
    required this.pageIndex,
    required this.pageCount,
    required this.image,
    required this.width,
    required this.height,
    required this.scale,
    required this.bandWidth,
    required this.timeline,
    required this.display,
  });

  final int pageIndex;
  final int pageCount;
  final ImageProvider? image;
  final double width;
  final double height;

  /// Page-image pixels to logical pixels; 0 while the size is unknown.
  final double scale;
  final double bandWidth;
  final ScoreTimeline timeline;
  final ValueListenable<Duration> display;

  @override
  Widget build(BuildContext context) {
    final provider = image;
    return SizedBox(
      width: width,
      height: height,
      child: Stack(
        children: [
          Positioned.fill(
            child: provider == null
                ? const ColoredBox(color: Colors.white)
                : Image(
                    image: provider,
                    fit: BoxFit.contain,
                    semanticLabel: PlaybackMessages.pageLabel(
                      pageIndex + 1,
                      pageCount,
                    ),
                    errorBuilder: (_, _, _) => const Center(
                      child: Icon(
                        Icons.broken_image_outlined,
                        color: AppTheme.playbackSubtle,
                      ),
                    ),
                  ),
          ),
          if (scale > 0)
            Positioned.fill(
              child: IgnorePointer(
                child: ValueListenableBuilder<Duration>(
                  valueListenable: display,
                  builder: (context, value, _) {
                    final band = timeline.positionAt(value);
                    if (band == null || band.pageIndex != pageIndex) {
                      return const SizedBox.shrink();
                    }
                    return Stack(
                      children: [
                        Positioned(
                          left: band.x * scale - bandWidth / 2,
                          top: band.top * scale,
                          width: bandWidth,
                          height: (band.bottom - band.top) * scale,
                          child: const DecoratedBox(
                            key: ValueKey('playback-band'),
                            decoration: BoxDecoration(
                              color: AppTheme.playbackBand,
                            ),
                          ),
                        ),
                      ],
                    );
                  },
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _ControlPanel extends StatelessWidget {
  const _ControlPanel({
    required this.display,
    required this.duration,
    required this.playing,
    required this.onPlayPause,
    required this.onToStart,
    required this.onToEnd,
    required this.onBack5,
    required this.onForward5,
    required this.onSeekChanged,
    required this.onSeekEnd,
    required this.onMixer,
    required this.onSpeed,
  });

  final ValueListenable<Duration> display;
  final Duration duration;
  final bool playing;
  final VoidCallback onPlayPause;
  final VoidCallback onToStart;
  final VoidCallback onToEnd;
  final VoidCallback onBack5;
  final VoidCallback onForward5;
  final ValueChanged<Duration> onSeekChanged;
  final ValueChanged<Duration> onSeekEnd;
  final VoidCallback onMixer;
  final VoidCallback onSpeed;

  static const double _radius = 24;
  static const double _playSize = 56;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final timeStyle = textTheme.bodyMedium?.copyWith(
      color: Colors.white,
      fontFeatures: const [FontFeature.tabularFigures()],
    );
    final maxMs = duration.inMilliseconds > 0 ? duration.inMilliseconds : 1;

    return DecoratedBox(
      decoration: const BoxDecoration(
        gradient: AppTheme.playbackPanelGradient,
        borderRadius: BorderRadius.vertical(top: Radius.circular(_radius)),
      ),
      child: SafeArea(
        top: false,
        child: MediaQuery.withClampedTextScaling(
          maxScaleFactor: 1.3,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    _CyanButton(
                      icon: Icons.skip_previous_outlined,
                      tooltip: PlaybackMessages.toStart,
                      onPressed: onToStart,
                    ),
                    _CyanButton(
                      icon: Icons.replay_5_rounded,
                      tooltip: PlaybackMessages.back5,
                      onPressed: onBack5,
                    ),
                    const SizedBox(width: 8),
                    IconButton.filled(
                      key: const ValueKey('play-pause'),
                      tooltip: playing
                          ? PlaybackMessages.pause
                          : PlaybackMessages.play,
                      onPressed: onPlayPause,
                      iconSize: 34,
                      style: IconButton.styleFrom(
                        backgroundColor: AppTheme.playbackAccent,
                        foregroundColor: AppTheme.playbackNavy,
                        fixedSize: const Size.square(_playSize),
                      ),
                      icon: Icon(
                        playing
                            ? Icons.pause_rounded
                            : Icons.play_arrow_rounded,
                      ),
                    ),
                    const SizedBox(width: 8),
                    _CyanButton(
                      icon: Icons.forward_5_rounded,
                      tooltip: PlaybackMessages.forward5,
                      onPressed: onForward5,
                    ),
                    _CyanButton(
                      icon: Icons.skip_next_outlined,
                      tooltip: PlaybackMessages.toLastBar,
                      onPressed: onToEnd,
                    ),
                  ],
                ),
                SliderTheme(
                  data: SliderTheme.of(context).copyWith(
                    activeTrackColor: Colors.white,
                    // Not in the mockup (its track is all white at 0:00):
                    // a dimmer unplayed part shows progress at a glance.
                    inactiveTrackColor: Colors.white.withValues(alpha: 0.45),
                    thumbColor: Colors.white,
                    overlayColor: Colors.white.withValues(alpha: 0.2),
                    trackHeight: 4,
                    thumbShape: const RoundSliderThumbShape(
                      enabledThumbRadius: 9,
                    ),
                    trackShape: const RoundedRectSliderTrackShape(),
                    showValueIndicator: ShowValueIndicator.never,
                  ),
                  child: ValueListenableBuilder<Duration>(
                    valueListenable: display,
                    builder: (context, value, _) => Slider(
                      key: const ValueKey('seek-bar'),
                      value: value.inMilliseconds.clamp(0, maxMs).toDouble(),
                      max: maxMs.toDouble(),
                      semanticFormatterCallback: (ms) => PlaybackMessages.time(
                        Duration(milliseconds: ms.round()),
                      ),
                      label: PlaybackMessages.seek,
                      onChanged: (ms) =>
                          onSeekChanged(Duration(milliseconds: ms.round())),
                      onChangeEnd: (ms) =>
                          onSeekEnd(Duration(milliseconds: ms.round())),
                    ),
                  ),
                ),
                Row(
                  children: [
                    ValueListenableBuilder<Duration>(
                      valueListenable: display,
                      builder: (context, value, _) => Text(
                        PlaybackMessages.time(
                          value > duration ? duration : value,
                        ),
                        key: const ValueKey('time-position'),
                        style: timeStyle,
                      ),
                    ),
                    Expanded(
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Flexible(
                            child: _PanelAction(
                              icon: const RotatedBox(
                                quarterTurns: 1,
                                child: Icon(
                                  Icons.tune_rounded,
                                  color: Colors.white,
                                  size: 28,
                                ),
                              ),
                              label: PlaybackMessages.voiceMixer,
                              onPressed: onMixer,
                            ),
                          ),
                          const SizedBox(width: 12),
                          Flexible(
                            child: _PanelAction(
                              icon: const CustomPaint(
                                size: Size.square(28),
                                painter: _MetronomePainter(),
                              ),
                              label: PlaybackMessages.speed,
                              onPressed: onSpeed,
                            ),
                          ),
                        ],
                      ),
                    ),
                    Text(
                      PlaybackMessages.time(duration),
                      key: const ValueKey('time-duration'),
                      style: timeStyle,
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _CyanButton extends StatelessWidget {
  const _CyanButton({
    required this.icon,
    required this.tooltip,
    required this.onPressed,
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: tooltip,
      onPressed: onPressed,
      iconSize: 30,
      color: AppTheme.playbackAccent,
      constraints: const BoxConstraints.tightFor(width: 48, height: 48),
      icon: Icon(icon),
    );
  }
}

class _PanelAction extends StatelessWidget {
  const _PanelAction({
    required this.icon,
    required this.label,
    required this.onPressed,
  });

  final Widget icon;
  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: label,
      excludeSemantics: true,
      child: InkWell(
        onTap: onPressed,
        borderRadius: BorderRadius.circular(12),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 48, minWidth: 48),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
            child: FittedBox(
              fit: BoxFit.scaleDown,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  icon,
                  const SizedBox(height: 2),
                  Text(
                    label,
                    maxLines: 1,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Colors.white,
                      fontWeight: FontWeight.w500,
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

/// A white outline metronome (no Material icon exists): a tapered body,
/// its base, and a pendulum tipped to the right.
class _MetronomePainter extends CustomPainter {
  const _MetronomePainter();

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;
    final stroke = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.stroke
      ..strokeWidth = w * 0.08
      ..strokeJoin = StrokeJoin.round
      ..strokeCap = StrokeCap.round;
    final body = Path()
      ..moveTo(w * 0.40, h * 0.08)
      ..lineTo(w * 0.60, h * 0.08)
      ..lineTo(w * 0.84, h * 0.92)
      ..lineTo(w * 0.16, h * 0.92)
      ..close();
    canvas
      ..drawPath(body, stroke)
      ..drawLine(Offset(w * 0.24, h * 0.70), Offset(w * 0.76, h * 0.70), stroke)
      ..drawLine(Offset(w * 0.50, h * 0.70), Offset(w * 0.86, h * 0.18), stroke)
      ..drawCircle(
        Offset(w * 0.73, h * 0.37),
        w * 0.07,
        Paint()..color = Colors.white,
      );
  }

  @override
  bool shouldRepaint(_MetronomePainter oldDelegate) => false;
}

class _ComingSoonSheet extends StatelessWidget {
  const _ComingSoonSheet({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(24, 8, 8, 32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Semantics(
                    header: true,
                    child: Text(
                      title,
                      style: textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: AppTheme.playbackTitle,
                      ),
                    ),
                  ),
                ),
                IconButton(
                  tooltip: PlaybackMessages.close,
                  onPressed: () => Navigator.of(context).pop(),
                  color: AppTheme.playbackTitle,
                  icon: const Icon(Icons.close_rounded),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              PlaybackMessages.comingSoon,
              style: textTheme.bodyLarge?.copyWith(
                color: AppTheme.playbackSubtle,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
