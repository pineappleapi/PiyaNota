import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/library_entry.dart';
import '../../models/score_summary.dart';
import '../../routes/app_routes.dart';
import '../../services/score_library_api.dart';
import '../../state/score_library_providers.dart';
import '../../state/session_actions.dart';
import '../../theme/app_theme.dart';
import '../../widgets/primary_pill_button.dart';
import '../auth/widgets/auth_error_banner.dart';
import 'library_messages.dart';
import 'widgets/library_bottom_nav.dart';
import 'widgets/library_header.dart';
import 'widgets/score_cards.dart';

/// PIYA-205 — Score Library, the home screen after login.
///
/// It is reached with `pushNamedAndRemoveUntil`, so it is the only route on
/// the stack: Android back exits the app rather than returning to Login.
class ScoreLibraryScreen extends ConsumerStatefulWidget {
  const ScoreLibraryScreen({super.key});

  @override
  ConsumerState<ScoreLibraryScreen> createState() => _ScoreLibraryScreenState();
}

class _ScoreLibraryScreenState extends ConsumerState<ScoreLibraryScreen> {
  final _searchController = TextEditingController();
  String _query = '';

  /// Scores with a delete request in flight, or confirmed deleted and
  /// animating out. Their rows stay on screen (PIYA-215 AC2: removed only
  /// after the server confirms) with taps disabled.
  final Set<int> _deletingIds = {};

  /// Trash-path deletions the server has confirmed, playing their exit
  /// transition before leaving the list. (Swiped rows are animated out by
  /// Dismissible itself.)
  final Set<int> _leavingIds = {};

  /// Scores whose delete confirmation dialog is open, so a double tap on
  /// the trash can't stack a second dialog.
  final Set<int> _confirmingIds = {};

  /// True while a Playback route is being pushed, so a double tap on a card
  /// opens it once.
  bool _openingScore = false;

  // Mockup: 32 dp side margins at 412 dp wide, header content at 26 dp,
  // first card 32 dp under the header, 18 dp between cards. Margins scale
  // down on narrow phones so cards keep usable text width.
  static const double _cardMarginFraction = 32 / 412;
  static const double _maxCardMargin = 32;
  static const double _minCardMargin = 16;
  static const double _headerInsetFromCards = 6;
  static const double _listTopGap = 32;
  static const double _cardGap = 18;
  static const double _stateMessageTopGap = 16;
  static const double _snackBarSideMargin = 16;
  static const double _swipeIconSize = 24;
  static const double _swipeIconInset = 24;
  static const double _swipeSpinnerSize = 20;
  static const double _swipeSpinnerStroke = 2;
  static const double _cardRadius = 12;
  static const Duration _swipeMoveDuration = Duration(milliseconds: 200);
  static const Duration _swipeResizeDuration = Duration(milliseconds: 220);

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  /// AC3: filters on every keystroke. PIYA-215 AC1 adds the debounce and a
  /// PIYA-308 call here; the screen only ever renders the filtered result.
  void _onSearchChanged(String value) => setState(() => _query = value);

  Future<void> _openScore(LibraryEntry entry) async {
    if (_openingScore) return;
    _openingScore = true;
    // Moves the score to the top of the library now; the real server
    // records the open itself when Playback fetches it (PIYA-308 AC8).
    ref.read(scoreLibraryProvider.notifier).markOpened(entry.scoreId);
    try {
      // AC7: the existing score's id only — Playback loads its stored
      // audio; nothing here triggers processing.
      await Navigator.of(context).pushNamed(
        AppRoutes.playback,
        arguments: PlaybackArguments(
          scoreId: entry.scoreId,
          title: entry.displayTitle,
        ),
      );
    } finally {
      _openingScore = false;
    }
  }

  void _openCapture() => Navigator.of(context).pushNamed(AppRoutes.capture);

  void _openSettings() => Navigator.of(context).pushNamed(AppRoutes.settings);

  Future<void> _returnToLogin() async {
    await endLocalSession(ref);
    if (!mounted) return;
    Navigator.of(context)
        .pushNamedAndRemoveUntil(AppRoutes.login, (_) => false);
  }

  /// Confirm dialog, then the server delete. Shared by the trash icon and
  /// swipe-to-delete so both behave identically. Returns true only when the
  /// score is gone server-side — deleted (200), or already gone (404) — and
  /// the row may leave; on cancel or any other failure the row stays (and a
  /// swiped row snaps back).
  Future<bool> _deleteScore(LibraryEntry entry) async {
    final scoreId = entry.scoreId;
    if (_confirmingIds.contains(scoreId) || _deletingIds.contains(scoreId)) {
      return false;
    }
    _confirmingIds.add(scoreId);
    final bool? confirmed;
    try {
      // PIYA-309 AC5: the API deletes without asking, so confirmation is
      // ours.
      confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => _DeleteScoreDialog(title: entry.displayTitle),
      );
    } finally {
      _confirmingIds.remove(scoreId);
    }
    if (confirmed != true || !mounted) return false;

    setState(() => _deletingIds.add(scoreId));
    String message;
    SnackBarAction? action;
    var gone = false;
    try {
      await ref.read(scoreLibraryProvider.notifier).deleteOnServer(scoreId);
      message = LibraryMessages.deleted(entry.displayTitle);
      gone = true;
    } on ScoreNotFoundException {
      message = LibraryMessages.deleteAlreadyGone;
      gone = true;
    } on SessionExpiredException {
      // Retrying can't fix a rejected token; give the way out right here.
      message = LibraryMessages.sessionExpired;
      action = SnackBarAction(
        label: LibraryMessages.logInAgain,
        onPressed: _returnToLogin,
      );
    } on ScoreLibraryNetworkException {
      message = LibraryMessages.deleteNetworkError;
    } on ScoreLibraryServerException {
      message = LibraryMessages.deleteServerError;
    } catch (e, stack) {
      // Anything unmapped still has to clear the row's spinner.
      if (kDebugMode) debugPrint('Score delete failed: $e\n$stack');
      message = LibraryMessages.deleteServerError;
    }
    if (!mounted) return gone;
    // A gone row keeps its disabled state until it has left the list.
    if (!gone) setState(() => _deletingIds.remove(scoreId));
    _showSnackBar(message, action: action);
    return gone;
  }

  /// [rowContext] belongs to the row that started the delete. If the row
  /// was unmounted while the request was in flight (e.g. a search hid it),
  /// its exit animation can never run, so the score is removed directly;
  /// otherwise a remounted row would keep its spinner forever.
  Future<void> _deleteViaTrash(
    LibraryEntry entry,
    BuildContext rowContext,
  ) async {
    final gone = await _deleteScore(entry);
    if (!gone || !mounted) return;
    if (rowContext.mounted) {
      setState(() => _leavingIds.add(entry.scoreId));
    } else {
      _finishRemoval(entry.scoreId);
    }
  }

  /// Swipe path of [_deleteViaTrash]. Dismissible only calls `onDismissed`
  /// if it is still mounted when `confirmDismiss` resolves, so a row hidden
  /// mid-request is removed here instead.
  Future<bool> _deleteViaSwipe(
    LibraryEntry entry,
    BuildContext rowContext,
  ) async {
    final gone = await _deleteScore(entry);
    if (gone && mounted && !rowContext.mounted) _finishRemoval(entry.scoreId);
    return gone;
  }

  void _finishRemoval(int scoreId) {
    if (!mounted) return;
    setState(() {
      _leavingIds.remove(scoreId);
      _deletingIds.remove(scoreId);
    });
    ref.read(scoreLibraryProvider.notifier).removeLocally(scoreId);
  }

  void _showSnackBar(String message, {SnackBarAction? action}) {
    final navHeight = LibraryBottomNav.heightFor(
      MediaQuery.paddingOf(context).bottom,
    );
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(message),
          action: action,
          behavior: SnackBarBehavior.floating,
          // Floats above the custom nav bar, which lives in the body and so
          // isn't known to Scaffold's own snackbar placement.
          margin: EdgeInsets.fromLTRB(
            _snackBarSideMargin,
            0,
            _snackBarSideMargin,
            navHeight,
          ),
        ),
      );
  }

  @override
  Widget build(BuildContext context) {
    final library = ref.watch(scoreLibraryProvider);
    final width = MediaQuery.sizeOf(context).width;
    final cardMargin = (width * _cardMarginFraction)
        .clamp(_minCardMargin, _maxCardMargin)
        .toDouble();
    final navHeight = LibraryBottomNav.heightFor(
      MediaQuery.paddingOf(context).bottom,
    );
    final keyboardHeight = MediaQuery.viewInsetsOf(context).bottom;
    // Hidden while searching: on a small phone at large text the Add Score
    // card would push every result below the fold (NFR-10). The nav bar's
    // Capture button still covers AC8.
    final showAddCard = _query.trim().isEmpty;

    final subtitle = switch (library) {
      AsyncData(:final value) =>
        value.isEmpty
            ? LibraryMessages.emptySubtitle
            : LibraryMessages.scoreCountSubtitle(value.length),
      AsyncError() => LibraryMessages.errorSubtitle,
      _ => LibraryMessages.loadingSubtitle,
    };

    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: Scaffold(
        backgroundColor: AppTheme.libraryBackground,
        // The nav bar stays put behind the keyboard; the list pads by the
        // keyboard height instead so every result is still reachable.
        resizeToAvoidBottomInset: false,
        body: Stack(
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                LibraryHeader(
                  subtitle: subtitle,
                  searchController: _searchController,
                  onSearchChanged: _onSearchChanged,
                  horizontalPadding: cardMargin - _headerInsetFromCards,
                ),
                Expanded(
                  child: ListView(
                    keyboardDismissBehavior:
                        ScrollViewKeyboardDismissBehavior.onDrag,
                    padding: EdgeInsets.fromLTRB(
                      cardMargin,
                      // Without the Add card, the first result carries its
                      // own card gap; keep it where the Add card sat.
                      showAddCard ? _listTopGap : _listTopGap - _cardGap,
                      cardMargin,
                      (keyboardHeight > navHeight
                              ? keyboardHeight
                              : navHeight) +
                          _cardGap,
                    ),
                    children: [
                      if (showAddCard) AddScoreCard(onTap: _openCapture),
                      ..._buildStateContent(library),
                    ],
                  ),
                ),
              ],
            ),
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: LibraryBottomNav(
                // Library is this screen.
                onLibrary: () {},
                onCapture: _openCapture,
                onSettings: _openSettings,
              ),
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _buildStateContent(AsyncValue<List<ScoreSummary>> library) {
    switch (library) {
      case AsyncData(:final value):
        // AC4: zero scores shows only the Add Score card, as in the mockup;
        // the header subtitle carries the empty-state message.
        if (value.isEmpty) return const [];
        final visible = filterLibraryEntries(
          buildLibraryEntries(value),
          _query,
        );
        if (visible.isEmpty) {
          return [
            const SizedBox(height: _cardGap + _stateMessageTopGap),
            _NoResultsMessage(query: _query),
          ];
        }
        final reduceMotion = MediaQuery.disableAnimationsOf(context);
        return [
          for (final entry in visible)
            // The Builder's context identifies this mount of the row, so a
            // delete that outlives it can tell (see _deleteViaTrash).
            Builder(
              key: ValueKey('row-${entry.scoreId}'),
              builder: (rowContext) => _RemovableRow(
                leaving: _leavingIds.contains(entry.scoreId),
                onRemoved: () => _finishRemoval(entry.scoreId),
                child: _buildDismissibleCard(
                  entry,
                  rowContext: rowContext,
                  reduceMotion: reduceMotion,
                ),
              ),
            ),
        ];
      case AsyncError(:final error):
        final sessionExpired = error is SessionExpiredException;
        return [
          const SizedBox(height: _cardGap),
          _LoadErrorPanel(
            message: _loadErrorMessage(error),
            actionLabel: sessionExpired
                ? LibraryMessages.logInAgain
                : LibraryMessages.retry,
            onAction: sessionExpired
                ? _returnToLogin
                : () => ref.read(scoreLibraryProvider.notifier).reload(),
          ),
        ];
      default:
        return const [SizedBox(height: _cardGap), _LoadingSkeletons()];
    }
  }

  Widget _buildDismissibleCard(
    LibraryEntry entry, {
    required BuildContext rowContext,
    required bool reduceMotion,
  }) {
    final scoreId = entry.scoreId;
    final isDeleting = _deletingIds.contains(scoreId);
    // The gap sits inside the Dismissible so it collapses with the card.
    const gap = EdgeInsets.only(top: _cardGap);
    return Dismissible(
      key: ValueKey('dismiss-$scoreId'),
      direction: isDeleting
          ? DismissDirection.none
          : DismissDirection.endToStart,
      // Same dialog and same wait-for-the-server as the trash icon:
      // returning false (cancel or failure) snaps the card back.
      confirmDismiss: (_) => _deleteViaSwipe(entry, rowContext),
      onDismissed: (_) => _finishRemoval(scoreId),
      movementDuration: reduceMotion ? Duration.zero : _swipeMoveDuration,
      resizeDuration: reduceMotion ? null : _swipeResizeDuration,
      background: Padding(
        padding: gap,
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: AppTheme.errorRed,
            borderRadius: BorderRadius.circular(_cardRadius),
          ),
          child: Align(
            alignment: Alignment.centerRight,
            child: Padding(
              padding: const EdgeInsets.only(right: _swipeIconInset),
              child: isDeleting
                  ? const SizedBox.square(
                      dimension: _swipeSpinnerSize,
                      child: CircularProgressIndicator(
                        strokeWidth: _swipeSpinnerStroke,
                        color: Colors.white,
                        semanticsLabel: LibraryMessages.deleting,
                      ),
                    )
                  : const Icon(
                      Icons.delete_rounded,
                      size: _swipeIconSize,
                      color: Colors.white,
                    ),
            ),
          ),
        ),
      ),
      child: Padding(
        padding: gap,
        child: ScoreCard(
          key: ValueKey(scoreId),
          entry: entry,
          isDeleting: isDeleting,
          onTap: () => _openScore(entry),
          onDelete: () => _deleteViaTrash(entry, rowContext),
        ),
      ),
    );
  }

  static String _loadErrorMessage(Object error) => switch (error) {
    SessionExpiredException() => LibraryMessages.sessionExpired,
    ScoreLibraryNetworkException() => LibraryMessages.loadNetworkError,
    _ => LibraryMessages.loadServerError,
  };
}

class _LoadingSkeletons extends StatelessWidget {
  const _LoadingSkeletons();

  static const int _count = 3;
  static const double _gap = 18;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      key: const Key('library-loading'),
      label: LibraryMessages.loadingSemantics,
      liveRegion: true,
      container: true,
      excludeSemantics: true,
      child: Column(
        children: [
          for (var i = 0; i < _count; i++) ...[
            if (i > 0) const SizedBox(height: _gap),
            const ScoreCardSkeleton(),
          ],
        ],
      ),
    );
  }
}

/// AC6 error state, reusing the auth screens' banner and pill button so
/// failures look the same across the app.
class _LoadErrorPanel extends StatelessWidget {
  const _LoadErrorPanel({
    required this.message,
    required this.actionLabel,
    required this.onAction,
  });

  final String message;
  final String actionLabel;
  final VoidCallback onAction;

  static const double _gap = 16;

  @override
  Widget build(BuildContext context) {
    return Column(
      key: const Key('library-error'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        AuthErrorBanner(message: message),
        const SizedBox(height: _gap),
        PrimaryPillButton(
          label: actionLabel,
          onPressed: onAction,
          // White 14 sp on the brand primaryBlue is 4.3:1, under AA; the
          // header's AA-darkened bottom stop (4.5:1) keeps it in the
          // library's own blue.
          backgroundColor: AppTheme.libraryHeaderBottom,
        ),
      ],
    );
  }
}

/// Search returned nothing although the library isn't empty — kept visibly
/// different from the AC4 empty state, which tells the user to capture.
class _NoResultsMessage extends StatelessWidget {
  const _NoResultsMessage({required this.query});

  final String query;

  static const double _headingToHintGap = 4;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Semantics(
      key: const Key('library-no-results'),
      liveRegion: true,
      container: true,
      child: Column(
        children: [
          Text(
            LibraryMessages.noResultsTitle,
            textAlign: TextAlign.center,
            style: textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w700,
              color: AppTheme.libraryCardTitle,
            ),
          ),
          const SizedBox(height: _headingToHintGap),
          Text(
            LibraryMessages.noResultsHint(query),
            textAlign: TextAlign.center,
            style: textTheme.bodyMedium?.copyWith(
              color: AppTheme.libraryScoreSubtitle,
            ),
          ),
        ],
      ),
    );
  }
}

/// A list row that can play a short collapse-and-fade exit once its score
/// is confirmed deleted via the trash icon, then reports [onRemoved] so the
/// caller drops it from the list. With reduce motion the exit is instant.
class _RemovableRow extends StatefulWidget {
  const _RemovableRow({
    required this.leaving,
    required this.onRemoved,
    required this.child,
  });

  final bool leaving;
  final VoidCallback onRemoved;
  final Widget child;

  @override
  State<_RemovableRow> createState() => _RemovableRowState();
}

class _RemovableRowState extends State<_RemovableRow>
    with SingleTickerProviderStateMixin {
  static const Duration _exitDuration = Duration(milliseconds: 220);

  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: _exitDuration,
    value: 1,
  );
  late final Animation<double> _curve = CurvedAnimation(
    parent: _controller,
    curve: Curves.easeInOut,
  );

  bool _reported = false;

  /// Reports the removal once, after the current frame: [onRemoved]
  /// changes the parent's state, which is not allowed mid-build or
  /// mid-dispose.
  void _reportRemovedAfterFrame() {
    if (_reported) return;
    _reported = true;
    final onRemoved = widget.onRemoved;
    WidgetsBinding.instance.addPostFrameCallback((_) => onRemoved());
  }

  @override
  void initState() {
    super.initState();
    // Remounted after its score was confirmed deleted (e.g. a search hid
    // it mid-exit): nothing to animate, just finish the removal.
    if (widget.leaving) _reportRemovedAfterFrame();
  }

  @override
  void didUpdateWidget(_RemovableRow oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.leaving || oldWidget.leaving) return;
    if (MediaQuery.disableAnimationsOf(context)) {
      _reportRemovedAfterFrame();
    } else {
      _controller.reverse().then((_) {
        if (mounted) _reportRemovedAfterFrame();
      });
    }
  }

  @override
  void dispose() {
    // Unmounted mid-exit (a search hid the row): the animation's future
    // never completes, so finish the removal here or the score would stay
    // in the list and the header count.
    if (widget.leaving) _reportRemovedAfterFrame();
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizeTransition(
      sizeFactor: _curve,
      alignment: Alignment.topCenter,
      child: FadeTransition(opacity: _curve, child: widget.child),
    );
  }
}

class _DeleteScoreDialog extends StatelessWidget {
  const _DeleteScoreDialog({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: Colors.white,
      title: const Text(LibraryMessages.deleteDialogTitle),
      content: Text(LibraryMessages.deleteDialogBody(title)),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          style: TextButton.styleFrom(
            foregroundColor: AppTheme.libraryScoreSubtitle,
          ),
          child: const Text(LibraryMessages.deleteCancel),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(true),
          style: TextButton.styleFrom(foregroundColor: AppTheme.errorRed),
          child: const Text(LibraryMessages.deleteConfirm),
        ),
      ],
    );
  }
}
