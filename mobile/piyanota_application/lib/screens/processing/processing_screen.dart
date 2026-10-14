import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/processing_status.dart';
import '../../routes/app_routes.dart';
import '../../state/processing_providers.dart';
import '../../state/session_actions.dart';
import '../../theme/app_theme.dart';
import '../../widgets/primary_pill_button.dart';
import '../retake/rephotograph.dart';
import 'processing_messages.dart';

/// Processing View (PIYA-207, SOW Module 2): follows one job through the
/// pipeline and opens Playback when it's done.
///
/// The progress itself lives in [processingJobsProvider], not here, so
/// leaving this screen ("Convert in Background", the back arrow, system
/// Back) never stops the job being followed.
///
/// Four outcomes look and act differently, because each needs a different
/// thing from the user: a page that can be retaken (AC5/AC7), a layout
/// that can't be fixed by retaking (AC6/AC7), connection trouble (wait or
/// Retry), and an expired session (log in).
class ProcessingScreen extends ConsumerStatefulWidget {
  const ProcessingScreen({super.key, required this.jobId, required this.title});

  final String jobId;

  /// The score's title, carried to Playback and to a retake.
  final String title;

  /// AC8 asks for Playback within 2 s of completion; the 100% card shows
  /// for this long first so the user sees it finished (mockup 3).
  static const Duration completionHold = Duration(milliseconds: 1200);

  /// How long the bar and percentage take to catch up with a new value.
  static const Duration percentTween = Duration(milliseconds: 600);

  @override
  ConsumerState<ProcessingScreen> createState() => _ProcessingScreenState();
}

class _ProcessingScreenState extends ConsumerState<ProcessingScreen> {
  /// True once this screen has shown the job still running. A job that's
  /// already complete when the screen opens goes straight to Playback;
  /// one that finishes in view shows 100% first.
  bool _sawProgress = false;

  /// Set while the cancel dialog is open or the cancel request is in
  /// flight, so a completion arriving meanwhile can't navigate out from
  /// under the dialog (it's handled once the cancel settles).
  bool _cancelling = false;
  bool _cancelRequestInFlight = false;

  /// Set once this screen has started leaving, so it never navigates twice.
  bool _leaving = false;
  Timer? _completionTimer;

  static const double _maxHeadingScale = 1.5;
  static const double _maxCardScale = 1.3;
  static const double _gutterFraction = 0.107; // 44 dp on the 412 dp mockup
  static const double _minGutter = 16;
  static const double _maxGutter = 44;

  @override
  void initState() {
    super.initState();
    // Providers can't change while this widget is building.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      ref
          .read(processingJobsProvider.notifier)
          .track(widget.jobId, title: widget.title);
      final job = ref.read(processingJobsProvider)[widget.jobId];
      if (job != null) _react(job);
    });
  }

  @override
  void dispose() {
    _completionTimer?.cancel();
    super.dispose();
  }

  TrackedJob? get _job => ref.read(processingJobsProvider)[widget.jobId];

  void _react(TrackedJob job) {
    if (_leaving) return;
    switch (job.phase) {
      case TrackedPhase.complete:
        if (!_cancelling) _complete(hold: _sawProgress);
      case TrackedPhase.sessionExpired:
        unawaited(_returnToLogin());
      case TrackedPhase.active ||
          TrackedPhase.reconnecting ||
          TrackedPhase.paused:
        if (job.status != null) _sawProgress = true;
      case TrackedPhase.failed ||
          TrackedPhase.cancelled ||
          TrackedPhase.notFound:
        // Shown in place by build().
        break;
    }
  }

  /// AC8: on to Playback, after [ProcessingScreen.completionHold] when the
  /// user watched it finish.
  void _complete({required bool hold}) {
    if (_leaving || _completionTimer != null) return;
    if (!hold) {
      unawaited(_finish());
      return;
    }
    _completionTimer = Timer(
      ProcessingScreen.completionHold,
      () => unawaited(_finish()),
    );
  }

  /// PIYA-207 AC8/AC11: with an `unreadable` voice the Re-photograph offer
  /// comes first (once per job), and routing waits for the answer. Only
  /// `render_failed` voices go straight to Playback.
  Future<void> _finish() async {
    if (!mounted || _leaving) return;
    final status = _job?.status;
    final unreadable = status?.unreadableVoices ?? const [];
    if (status == null ||
        unreadable.isEmpty ||
        await RephotographOfferPrefs.isAnswered(widget.jobId)) {
      _openPlayback();
      return;
    }
    if (!mounted || _leaving) return;
    _leaving = true;
    final navigator = Navigator.of(context);
    final choice = await showRephotographOffer(
      context,
      voices: unreadable,
      playable: status.playableVoiceCount,
    );
    if (!mounted) return;
    switch (choice) {
      case null:
        // System Back: to the library, not answered, offered again on
        // the next tap of the card (AC11).
        _goToLibrary(navigator);
      case RephotographChoice.continuePlayback:
        await RephotographOfferPrefs.markAnswered(widget.jobId);
        _leaving = false;
        _openPlayback();
      case RephotographChoice.rephotograph:
        await RephotographOfferPrefs.markAnswered(widget.jobId);
        if (!mounted) return;
        await startWholeRetake(
          context,
          ref,
          jobId: widget.jobId,
          title: widget.title,
          details: status.details,
          retakeOfScoreId: status.scoreId,
        );
    }
  }

  void _openPlayback() {
    if (!mounted || _leaving) return;
    _leaving = true;
    final scoreId = _job?.status?.scoreId;
    final navigator = Navigator.of(context);
    if (scoreId == null) {
      // PIYA-102 doesn't return a scoreId yet (contract gap): the score is
      // in the library, so send the user there rather than strand them.
      _snack(ProcessingMessages.readyInLibrary);
      _goToLibrary(navigator);
      return;
    }
    navigator.pushReplacementNamed(
      AppRoutes.playback,
      arguments: PlaybackArguments(scoreId: scoreId, title: widget.title),
    );
  }

  /// "Convert in Background", the back arrow and system Back all land
  /// here. The job stays tracked.
  void _backToLibrary() {
    if (_leaving) return;
    _leaving = true;
    _completionTimer?.cancel();
    _goToLibrary(Navigator.of(context));
  }

  /// Pops back to the library already under this screen; if there isn't
  /// one (opened some other way), replaces this screen with it.
  static void _goToLibrary(NavigatorState navigator) {
    var found = false;
    navigator.popUntil((route) {
      if (route.settings.name == AppRoutes.scoreLibrary) {
        found = true;
        return true;
      }
      return route.isFirst;
    });
    if (!found) navigator.pushReplacementNamed(AppRoutes.scoreLibrary);
  }

  Future<void> _returnToLogin() async {
    if (_leaving) return;
    _leaving = true;
    _completionTimer?.cancel();
    final navigator = Navigator.of(context);
    await endLocalSession(ref);
    _snack(ProcessingMessages.sessionExpired);
    navigator.pushNamedAndRemoveUntil(AppRoutes.login, (_) => false);
  }

  Future<void> _confirmCancel() async {
    if (_cancelling || _leaving) return;
    setState(() => _cancelling = true);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text(ProcessingMessages.cancelTitle),
        content: const Text(ProcessingMessages.cancelBody),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text(ProcessingMessages.keepScanning),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: TextButton.styleFrom(foregroundColor: AppTheme.errorRed),
            child: const Text(ProcessingMessages.confirmCancel),
          ),
        ],
      ),
    );
    if (!mounted) return;
    if (confirmed != true) {
      setState(() => _cancelling = false);
      // It may have finished while the dialog was open.
      if (_job case final job?) _react(job);
      return;
    }
    setState(() => _cancelRequestInFlight = true);
    final outcome = await ref
        .read(processingJobsProvider.notifier)
        .cancel(widget.jobId);
    if (!mounted) return;
    setState(() {
      _cancelling = false;
      _cancelRequestInFlight = false;
    });
    switch (outcome) {
      case CancelOutcome.cancelled:
        _snack(ProcessingMessages.scanCancelled);
        _backToLibrary();
      case CancelOutcome.notFound:
        _backToLibrary();
      case CancelOutcome.sessionExpired:
        await _returnToLogin();
      case CancelOutcome.failed:
        // The job may have finished while the dialog was open or the
        // request was out. _react was skipped then (cancelling), and the
        // tracker has stopped polling a finished job, so nothing else
        // would ever move this screen on from 100%.
        final job = _job;
        final finished =
            job != null &&
            (job.phase == TrackedPhase.complete ||
                job.phase == TrackedPhase.failed);
        _snack(
          finished
              ? ProcessingMessages.alreadyFinished
              : ProcessingMessages.cancelFailed,
        );
        if (job != null) _react(job);
      case CancelOutcome.alreadyFinished:
        // The tracker has re-polled: complete goes on to Playback, failed
        // shows its view.
        _snack(ProcessingMessages.alreadyFinished);
        if (_job case final job?) {
          _sawProgress = true;
          _react(job);
        }
    }
  }

  /// PIYA-207 AC7 `incompleteVoiceSequence`: the whole score (AC12). The
  /// failed scan's card is replaced by the new one, so no score id.
  void _retakeWhole() {
    if (_leaving) return;
    _leaving = true;
    unawaited(
      startWholeRetake(
        context,
        ref,
        jobId: widget.jobId,
        title: widget.title,
        details: _job?.status?.details,
      ),
    );
  }

  void _retake(int pageIndex) {
    Navigator.of(context).pushNamed(
      AppRoutes.captureRetake,
      arguments: CaptureRetakeArguments(
        jobId: widget.jobId,
        pageIndex: pageIndex,
        title: widget.title,
      ),
    );
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<TrackedJob?>(
      processingJobsProvider.select((jobs) => jobs[widget.jobId]),
      (_, next) {
        if (next != null) _react(next);
      },
    );
    final job = ref.watch(
      processingJobsProvider.select((jobs) => jobs[widget.jobId]),
    );
    final width = MediaQuery.sizeOf(context).width;
    final gutter = (width * _gutterFraction).clamp(_minGutter, _maxGutter);

    final Widget body = switch (job?.phase) {
      TrackedPhase.failed => _FailureView(
        heading:
            job?.status?.failureReason == FailureReason.unsupportedStaffLayout
            ? ProcessingMessages.unsupportedHeading
            : ProcessingMessages.failedHeading,
        status: job!.status,
        onRetake: _retake,
        onRetakeWhole: _retakeWhole,
        onBack: _backToLibrary,
      ),
      TrackedPhase.notFound => _FailureView(
        heading: ProcessingMessages.notFoundHeading,
        body: ProcessingMessages.notFoundBody,
        onBack: _backToLibrary,
      ),
      TrackedPhase.cancelled => _FailureView(
        heading: ProcessingMessages.cancelledHeading,
        body: ProcessingMessages.cancelledBody,
        onBack: _backToLibrary,
      ),
      _ => _ProgressView(
        job: job,
        cancelling: _cancelRequestInFlight,
        onCancel: job?.phase == TrackedPhase.complete || _leaving
            ? null
            : _confirmCancel,
        onBackground: _backToLibrary,
        onRetry: () =>
            ref.read(processingJobsProvider.notifier).retry(widget.jobId),
        headingScale: _maxHeadingScale,
        cardScale: _maxCardScale,
      ),
    };

    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _backToLibrary();
      },
      child: Scaffold(
        backgroundColor: Colors.white,
        body: SafeArea(
          child: CustomScrollView(
            slivers: [
              SliverFillRemaining(
                hasScrollBody: false,
                child: Padding(
                  padding: EdgeInsets.fromLTRB(gutter, 4, gutter, 16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Align(
                        alignment: Alignment.centerLeft,
                        child: IconButton(
                          tooltip: ProcessingMessages.backToLibrary,
                          onPressed: _backToLibrary,
                          color: AppTheme.onboardingHeadingDark,
                          icon: const Icon(Icons.arrow_back_rounded),
                        ),
                      ),
                      Expanded(child: body),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ProgressView extends StatelessWidget {
  const _ProgressView({
    required this.job,
    required this.cancelling,
    required this.onCancel,
    required this.onBackground,
    required this.onRetry,
    required this.headingScale,
    required this.cardScale,
  });

  final TrackedJob? job;
  final bool cancelling;
  final VoidCallback? onCancel;
  final VoidCallback onBackground;
  final VoidCallback onRetry;
  final double headingScale;
  final double cardScale;

  static const double _cancelFontSize = 18;
  static const double _buttonMinHeight = 48;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final status = job?.status;
    final phase = job?.phase ?? TrackedPhase.active;
    final paused = phase == TrackedPhase.paused;
    final helper = switch (phase) {
      TrackedPhase.reconnecting => ProcessingMessages.reconnecting,
      _ when job?.isStalled ?? false => ProcessingMessages.stalled,
      _ => ProcessingMessages.helper,
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Spacer(flex: 5),
        MediaQuery.withClampedTextScaling(
          maxScaleFactor: headingScale,
          child: Semantics(
            header: true,
            child: Text(
              ProcessingMessages.heading,
              style: textTheme.headlineSmall?.copyWith(
                fontSize: 26,
                fontWeight: FontWeight.w700,
                color: AppTheme.onboardingHeadingDark,
              ),
            ),
          ),
        ),
        // Live, so a screen reader hears each stage change, but not every
        // percentage tick (that's in the card's label).
        Semantics(
          liveRegion: true,
          child: Text(
            ProcessingMessages.subtitle(status?.stage),
            style: textTheme.titleMedium?.copyWith(
              fontSize: 18,
              fontWeight: FontWeight.w400,
              color: AppTheme.onboardingBody,
            ),
          ),
        ),
        const SizedBox(height: 12),
        MediaQuery.withClampedTextScaling(
          maxScaleFactor: headingScale,
          child: _ProgressCard(
            percent: job?.percent ?? 0,
            status: status,
            showEstimate:
                status?.stage != ProcessingStage.complete &&
                phase != TrackedPhase.complete,
            percentScale: cardScale,
          ),
        ),
        const SizedBox(height: 8),
        if (paused)
          _PausedPanel(onRetry: onRetry)
        else
          Text(
            helper,
            textAlign: TextAlign.center,
            style: textTheme.bodySmall?.copyWith(
              fontSize: 11,
              color: AppTheme.onboardingBody,
            ),
          ),
        const Spacer(flex: 6),
        const SizedBox(height: 16),
        Center(
          child: TextButton.icon(
            onPressed: cancelling ? null : onCancel,
            style: TextButton.styleFrom(
              foregroundColor: AppTheme.processingCancel,
              minimumSize: const Size(_buttonMinHeight, _buttonMinHeight),
              textStyle: textTheme.titleMedium?.copyWith(
                fontSize: _cancelFontSize,
                fontWeight: FontWeight.w500,
              ),
            ),
            icon: const Icon(Icons.close_rounded),
            label: Text(
              cancelling
                  ? ProcessingMessages.cancelling
                  : ProcessingMessages.cancelScan,
            ),
          ),
        ),
        const SizedBox(height: 8),
        OutlinedButton(
          onPressed: onBackground,
          style: OutlinedButton.styleFrom(
            foregroundColor: AppTheme.processingSecondary,
            side: const BorderSide(color: AppTheme.processingSecondary),
            minimumSize: const Size.fromHeight(_buttonMinHeight),
            shape: const StadiumBorder(),
            textStyle: textTheme.labelLarge?.copyWith(
              fontWeight: FontWeight.w600,
            ),
          ),
          child: const Text(
            ProcessingMessages.convertInBackground,
            textAlign: TextAlign.center,
          ),
        ),
      ],
    );
  }
}

/// The gradient card from the mockups: big percentage, page and time left,
/// and the bar.
class _ProgressCard extends StatelessWidget {
  const _ProgressCard({
    required this.percent,
    required this.status,
    required this.showEstimate,
    required this.percentScale,
  });

  final int percent;
  final ProcessingStatus? status;
  final bool showEstimate;
  final double percentScale;

  static const double _radius = 10;
  static const double _trackHeight = 4;
  static const double _percentFontSize = 40;
  static const double _pageFontSize = 12;
  static const double _etaFontSize = 13;
  static const double _maxPercent = 100;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final current = status?.currentPage;
    final total = status?.totalPages;
    final showPage = current != null && total != null;
    final seconds = showEstimate ? status?.estimatedRemainingSeconds : null;

    return Semantics(
      container: true,
      label: ProcessingMessages.cardSemantics(
        percent: percent,
        currentPage: showPage ? current : null,
        totalPages: showPage ? total : null,
        secondsLeft: seconds,
      ),
      child: ExcludeSemantics(
        child: DecoratedBox(
          decoration: BoxDecoration(
            gradient: AppTheme.processingCardGradient,
            borderRadius: BorderRadius.circular(_radius),
          ),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
            child: TweenAnimationBuilder<double>(
              tween: Tween<double>(end: percent.toDouble()),
              duration: ProcessingScreen.percentTween,
              curve: Curves.easeOut,
              builder: (context, value, _) => Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      MediaQuery.withClampedTextScaling(
                        maxScaleFactor: percentScale,
                        child: Text(
                          ProcessingMessages.percent(value.round()),
                          style: textTheme.displaySmall?.copyWith(
                            fontSize: _percentFontSize,
                            fontWeight: FontWeight.w700,
                            color: Colors.white,
                            height: 1.2,
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            if (showPage)
                              Text(
                                ProcessingMessages.page(current, total),
                                textAlign: TextAlign.end,
                                style: textTheme.labelSmall?.copyWith(
                                  fontSize: _pageFontSize,
                                  fontWeight: FontWeight.w700,
                                  color: AppTheme.processingPageText,
                                ),
                              ),
                            if (seconds != null)
                              Text(
                                ProcessingMessages.timeLeft(seconds),
                                textAlign: TextAlign.end,
                                style: textTheme.labelMedium?.copyWith(
                                  fontSize: _etaFontSize,
                                  fontWeight: FontWeight.w600,
                                  color: Colors.white,
                                ),
                              ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  LinearProgressIndicator(
                    value: value / _maxPercent,
                    minHeight: _trackHeight,
                    color: Colors.white,
                    backgroundColor: AppTheme.processingTrack,
                    borderRadius: BorderRadius.circular(_trackHeight / 2),
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

/// Spec §7 "No internet": after [ProcessingTiming.pauseAfter] of failed
/// polls, stop implying progress and hand the user a Retry.
class _PausedPanel extends StatelessWidget {
  const _PausedPanel({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Semantics(
      liveRegion: true,
      container: true,
      child: Column(
        children: [
          const Icon(Icons.wifi_off_rounded, color: AppTheme.onboardingBody),
          const SizedBox(height: 4),
          Text(
            ProcessingMessages.pausedTitle,
            textAlign: TextAlign.center,
            style: textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w700,
              color: AppTheme.onboardingHeadingDark,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            ProcessingMessages.pausedBody,
            textAlign: TextAlign.center,
            style: textTheme.bodySmall?.copyWith(
              color: AppTheme.onboardingBody,
            ),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: onRetry,
            style: OutlinedButton.styleFrom(
              foregroundColor: AppTheme.processingSecondary,
              side: const BorderSide(color: AppTheme.processingSecondary),
              minimumSize: const Size(48, 48),
              shape: const StadiumBorder(),
            ),
            icon: const Icon(Icons.refresh_rounded),
            label: const Text(ProcessingMessages.retry),
          ),
        ],
      ),
    );
  }
}

/// AC5–AC7: replaces the progress view entirely, so a failure never reads
/// as "still loading". Copy is per reason; actions depend on whether a
/// retake can help.
class _FailureView extends StatelessWidget {
  const _FailureView({
    required this.heading,
    required this.onBack,
    this.status,
    this.body,
    this.onRetake,
    this.onRetakeWhole,
  });

  final String heading;
  final ProcessingStatus? status;

  /// Fixed copy for the non-pipeline cases (gone, cancelled); otherwise
  /// worded from [status].
  final String? body;
  final ValueChanged<int>? onRetake;

  /// AC7/AC12: re-photograph the whole score.
  final VoidCallback? onRetakeWhole;
  final VoidCallback onBack;

  static const double _iconSize = 48;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final reason = status?.failureReason ?? FailureReason.unknown;
    // PIYA-102 `pageIndex` is assumed to count from 0 like PIYA-101's
    // (open contract question, PIYA-216); people count from 1.
    final pageIndex = status?.failedPageIndex;
    final page = pageIndex == null ? null : pageIndex + 1;
    final canRetake =
        body == null &&
        reason.isRetakeable &&
        pageIndex != null &&
        onRetake != null;
    final canRetakeWhole =
        body == null && reason.isWholeRetakeable && onRetakeWhole != null;
    final unsupported = reason == FailureReason.unsupportedStaffLayout;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Spacer(flex: 3),
        Icon(
          unsupported
              ? Icons.view_stream_outlined
              : Icons.error_outline_rounded,
          size: _iconSize,
          color: AppTheme.errorRed,
        ),
        const SizedBox(height: 12),
        MediaQuery.withClampedTextScaling(
          maxScaleFactor: 1.5,
          child: Semantics(
            header: true,
            child: Text(
              heading,
              textAlign: TextAlign.center,
              style: textTheme.headlineSmall?.copyWith(
                fontSize: 24,
                fontWeight: FontWeight.w700,
                color: AppTheme.onboardingHeadingDark,
              ),
            ),
          ),
        ),
        const SizedBox(height: 12),
        Semantics(
          liveRegion: true,
          child: Text(
            body ?? ProcessingMessages.failureBody(reason, page),
            textAlign: TextAlign.center,
            style: textTheme.bodyLarge?.copyWith(
              color: AppTheme.onboardingBody,
            ),
          ),
        ),
        if (body == null && unsupported && page != null) ...[
          const SizedBox(height: 8),
          Text(
            ProcessingMessages.foundOnPage(page),
            textAlign: TextAlign.center,
            style: textTheme.bodyMedium?.copyWith(
              color: AppTheme.onboardingBody,
            ),
          ),
        ],
        if (canRetake || canRetakeWhole) ...[
          const SizedBox(height: 16),
          Text(
            ProcessingMessages.retakeTipsTitle,
            style: textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w700,
              color: AppTheme.onboardingHeadingDark,
            ),
          ),
          const SizedBox(height: 4),
          for (final tip in ProcessingMessages.retakeTips)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 2, right: 8),
                    child: Icon(
                      Icons.check_rounded,
                      size: 18,
                      color: AppTheme.processingSecondary,
                    ),
                  ),
                  Expanded(
                    child: Text(
                      tip,
                      style: textTheme.bodyMedium?.copyWith(
                        color: AppTheme.onboardingBody,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
        const Spacer(flex: 4),
        const SizedBox(height: 16),
        if (canRetake || canRetakeWhole) ...[
          PrimaryPillButton(
            label: canRetake
                ? ProcessingMessages.retakePage(page!)
                : RephotographMessages.rephotograph,
            onPressed: canRetake ? () => onRetake!(pageIndex) : onRetakeWhole,
            // White on the brand blue is 4.3:1; this blue passes 4.5:1.
            backgroundColor: AppTheme.processingSecondary,
          ),
          const SizedBox(height: 8),
          OutlinedButton(
            onPressed: onBack,
            style: OutlinedButton.styleFrom(
              foregroundColor: AppTheme.processingSecondary,
              side: const BorderSide(color: AppTheme.processingSecondary),
              minimumSize: const Size.fromHeight(48),
              shape: const StadiumBorder(),
            ),
            child: const Text(ProcessingMessages.backToLibrary),
          ),
        ] else
          PrimaryPillButton(
            label: ProcessingMessages.backToLibrary,
            onPressed: onBack,
            backgroundColor: AppTheme.processingSecondary,
          ),
      ],
    );
  }
}
