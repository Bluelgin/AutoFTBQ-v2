package dev.autoftbq.agent.bridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.mojang.logging.LogUtils;
import dev.autoftbq.agent.compat.ftbq.v2001.FTBQ2001ContextAdapter;
import dev.autoftbq.agent.client.AgentContextSelection;
import dev.autoftbq.agent.compat.ftbq.v2001.FTBQ2001QueryExecutor;
import dev.autoftbq.agent.platform.GamePlatform;
import dev.autoftbq.agent.platform.ProposalApplicationResult;
import dev.autoftbq.agent.platform.ProposalUndoResult;
import dev.autoftbq.agent.platform.ServerSecurityState;
import net.minecraft.client.Minecraft;
import net.minecraftforge.fml.ModList;
import net.minecraftforge.versions.forge.ForgeVersion;
import org.slf4j.Logger;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.TimeUnit;

public final class BridgeClient {
    private static final Logger LOGGER = LogUtils.getLogger();
    public static final BridgeClient INSTANCE = new BridgeClient();
    private static final Gson GSON = new Gson();
    private static final Gson PRETTY_GSON = new GsonBuilder().setPrettyPrinting().create();
    private static final String CLIENT_ID = loadPersistentClientId();

    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(2))
            .build();
    private volatile String status = "尚未连接 Studio";
    private volatile String sessionId = "";
    private volatile String projectId = "";
    private volatile String conversationId = "";
    private volatile String lastUploadedBookRevision = "";
    private volatile String activeWorldId = "";
    private volatile int revision = 0;
    private volatile BridgeDiscovery activeDiscovery;
    private final AtomicBoolean inFlight = new AtomicBoolean(false);
    private volatile String requestId = "";
    private volatile boolean pauseRequested;

    public boolean isPauseRequested() { return pauseRequested; }
    public boolean canPauseRequest() { return !requestId.isBlank() && isBusy(); }
    public void togglePauseRequest() {
        String current = requestId;
        BridgeDiscovery discovery = activeDiscovery;
        if (current.isBlank() || discovery == null) return;
        boolean pause = !pauseRequested;
        CompletableFuture.runAsync(() -> {
            try {
                JsonObject response = post(discovery, "/v1/requests/" + current + (pause ? "/pause" : "/resume"), new JsonObject());
                if (current.equals(requestId)) pauseRequested = response.has("pause_requested") && response.get("pause_requested").getAsBoolean();
            } catch (Exception error) {
                setStatus("暂停/继续失败：" + safeMessage(error));
            }
        });
    }
    private volatile String activePrompt = "";
    private volatile String result = "";
    private volatile String proposalId = "";
    private volatile String proposalPreview = "";
    private volatile boolean proposalPending = false;
    private volatile String proposalOperationsJson = "";
    private volatile String proposalBaseServerRevision = "";
    private volatile String proposalAgentResult = "";
    private volatile Set<String> proposalAffectedQuestIds = Set.of();
    private volatile boolean undoAvailable = false;
    private volatile String undoProposalId = "";
    private volatile String undoBookRevision = "";
    private final List<HistoryEntry> history = new CopyOnWriteArrayList<>();
    private final java.util.LinkedHashMap<String, String[]> sharedHistory = new java.util.LinkedHashMap<>();
    private volatile long sharedEventCursor = 0L;
    private final Deque<PendingApplicationReport> pendingReports = new ArrayDeque<>();
    private final ScheduledExecutorService reportRetry = Executors.newSingleThreadScheduledExecutor(runnable -> {
        Thread thread = new Thread(runnable, "AutoFTBQ-application-report-retry");
        thread.setDaemon(true);
        return thread;
    });
    private volatile int historyIndex = -1;

    private BridgeClient() {
        reportRetry.scheduleWithFixedDelay(this::flushPendingReportsQuietly,
                3, 3, TimeUnit.SECONDS);
    }

    public String status() {
        return status;
    }

    public String result() {
        int index = historyIndex;
        if (index >= 0 && index < history.size()) {
            HistoryEntry entry = history.get(index);
            return "你：" + entry.prompt() + "\n\nAgent：" + entry.text();
        }
        String response = proposalPreview.isBlank() ? result : result + "\n\n" + proposalPreview;
        if (activePrompt.isBlank()) return response;
        return "你：" + activePrompt + (response.isBlank() ? "" : "\n\nAgent：" + response);
    }

    public boolean hasPendingProposal() {
        return historyIndex < 0 && proposalPending;
    }

    public boolean isProposalAffectedQuest(String questId) {
        return proposalPending && proposalAffectedQuestIds.contains(questId);
    }

    public boolean canUndo() {
        return historyIndex < 0 && undoAvailable;
    }

    public String historyPosition() {
        int index = historyIndex;
        return index < 0 ? "" : (index + 1) + " / " + history.size();
    }

    public boolean hasHistory() {
        return !history.isEmpty();
    }

    public boolean isViewingHistory() {
        return historyIndex >= 0;
    }

    public void previousHistory() {
        if (history.isEmpty()) return;
        historyIndex = historyIndex < 0 ? history.size() - 1 : Math.max(0, historyIndex - 1);
    }

    public void nextHistory() {
        if (historyIndex < 0) return;
        historyIndex = historyIndex >= history.size() - 1 ? -1 : historyIndex + 1;
    }

    public boolean isBusy() {
        return inFlight.get();
    }

    public void connectAndSync() {
        if (!inFlight.compareAndSet(false, true)) {
            return;
        }
        status = "正在连接 AutoFTBQ Studio…";
        CompletableFuture.runAsync(() -> {
            try {
                BridgeDiscovery discovery = ensureSession();
                flushPendingReports();
                JsonObject context = captureContext(++revision);
                updateActiveWorld(context);
                applyContextIdentity(post(discovery, "/v1/context", context));
                uploadBookSnapshotIfChanged(discovery, context);
                syncSharedTimeline(discovery);
                int selectedQuests = context.getAsJsonArray("selected_quests").size();
                int selectedChapters = context.getAsJsonArray("selected_chapters").size();
                boolean canEdit = context.getAsJsonObject("book_summary").has("server_can_edit")
                        && context.getAsJsonObject("book_summary").get("server_can_edit").getAsBoolean();
                setStatus(canEdit
                        ? "已连接 Studio · 上下文 " + selectedChapters + " 章 / "
                        + selectedQuests + " 任务"
                        : "已连接 Studio · 服务器未授予 FTBQ 编辑权限");
            } catch (Exception error) {
                setStatus("连接失败：" + safeMessage(error));
            } finally {
                inFlight.set(false);
            }
        });
    }

    public void submitRequest(String prompt) {
        submitRequest(prompt, null);
    }

    public void submitSketch(String prompt, String image, String mode) {
        JsonObject sketch = new JsonObject();
        sketch.addProperty("image_data_url", image);
        sketch.addProperty("mode", mode);
        submitRequest(prompt, sketch);
    }

    private void submitRequest(String prompt, JsonObject sketch) {
        String text = prompt == null ? "" : prompt.trim();
        if (text.isBlank() || !inFlight.compareAndSet(false, true)) {
            return;
        }
        result = "";
        activePrompt = text;
        historyIndex = -1;
        proposalId = "";
        proposalPreview = "";
        proposalPending = false;
        proposalOperationsJson = "";
        proposalBaseServerRevision = "";
        proposalAgentResult = "";
        proposalAffectedQuestIds = Set.of();
        undoAvailable = false;
        undoProposalId = "";
        undoBookRevision = "";
        status = "正在同步 FTBQ 选区…";
        CompletableFuture.runAsync(() -> {
            boolean applicationOwnsFlight = false;
            try {
                BridgeDiscovery discovery = ensureSession();
                flushPendingReports();
                JsonObject context = captureSynchronizedContext(discovery, 15_000L);
                int contextRevision = context.get("revision").getAsInt();
                uploadBookSnapshotIfChanged(discovery, context);
                JsonObject request = new JsonObject();
                request.addProperty("session_id", sessionId);
                request.addProperty("context_revision", contextRevision);
                request.addProperty("prompt", text);
                if (sketch != null) {
                    if (!supportsSketch) throw new IllegalStateException("Studio 版本不支持画板图片，请更新并重启 Studio；草稿已保留");
                    request.add("layout_sketch", sketch);
                }
                JsonObject accepted = post(discovery, "/v1/requests", request);
                requestId = accepted.get("request_id").getAsString();
                pauseRequested = false;
                pollRequest(discovery, requestId, text);
                if (proposalPending) {
                    applicationOwnsFlight = decideProposal(true, true);
                }
            } catch (Exception error) {
                setStatus("请求失败：" + safeMessage(error));
                LOGGER.warn("AutoFTBQ Agent request interrupted or failed: {}", safeMessage(error));
            } finally {
                requestId = "";
                pauseRequested = false;
                if (!applicationOwnsFlight) inFlight.set(false);
            }
        });
    }

    public void cancelRequest() {
        String current = requestId;
        BridgeDiscovery discovery = activeDiscovery;
        if (current.isBlank() || discovery == null) {
            return;
        }
        setStatus("正在取消…");
        CompletableFuture.runAsync(() -> {
            try {
                post(discovery, "/v1/requests/" + current + "/cancel", new JsonObject());
            } catch (Exception error) {
                setStatus("取消失败：" + safeMessage(error));
            }
        });
    }

    public void pollStudioTransactions() {
        if (!inFlight.compareAndSet(false, true)) return;
        CompletableFuture.runAsync(() -> {
            try {
                BridgeDiscovery discovery = ensureSession();
                processNextStudioTransaction(discovery);
            } catch (Exception error) {
                setStatus("同步失败：" + safeMessage(error));
            } finally {
                inFlight.set(false);
            }
        });
    }

    private void processNextStudioTransaction(BridgeDiscovery discovery) throws Exception {
                JsonObject envelope = get(discovery,
                        "/v1/studio-transactions/next?session_id=" + sessionId);
                if (!envelope.has("transaction") || envelope.get("transaction").isJsonNull()) {
                    syncSharedTimeline(discovery);
                    return;
                }
                JsonObject transaction = envelope.getAsJsonObject("transaction");
                String currentProposalId = transaction.get("proposal_id").getAsString();
                String expectedRevision = transaction.get(
                        "base_server_book_revision").getAsString();
                String operationsJson = GSON.toJson(transaction.get("operations"));
                String preview = formatProposalPreview(
                        transaction.get("summary").getAsString(),
                        transaction.getAsJsonArray("operations"));
                proposalId = currentProposalId;
                proposalBaseServerRevision = expectedRevision;
                proposalOperationsJson = operationsJson;
                setProposalPreview(preview);
                setStatus("正在应用后端 Agent 修改…");
                ProposalApplicationResult applied = applyProposalWithRetry(
                        currentProposalId, expectedRevision, operationsJson);
                if (applied.success()) {
                    undoProposalId = currentProposalId;
                    undoBookRevision = applied.bookRevision();
                    undoAvailable = true;
                    setProposalPreview(preview.replace(
                            "修改记录（正在自动提交）", "修改记录（服务器已应用）"));
                }
                JsonObject application = new JsonObject();
                application.addProperty("session_id", sessionId);
                application.addProperty("status", applied.status());
                application.addProperty("message", applied.message());
                application.addProperty("server_book_revision", applied.bookRevision());
                application.add("id_map", GSON.fromJson(applied.idMapJson(), JsonObject.class));
                reportApplication(discovery, currentProposalId, application);
                if (applied.success()) {
                    JsonObject refreshed = captureContext(++revision);
                    applyContextIdentity(post(discovery, "/v1/context", refreshed));
                    uploadBookSnapshotIfChanged(discovery, refreshed);
                    syncSharedTimeline(discovery);
                    FTBQ2001ContextAdapter.refreshEmbeddedEditor();
                    setStatus("后端修改已生效 · 可撤回");
                } else {
                    setStatus("Studio 同步失败：" + applied.message());
                }
    }

    private volatile boolean supportsSketch;

    private BridgeDiscovery ensureSession() throws Exception {
        BridgeDiscovery discovery = BridgeDiscovery.load();
        if (!discovery.equals(activeDiscovery) || sessionId.isBlank()) {
            JsonObject response = post(discovery, "/v1/handshake", createHandshake());
            supportsSketch = response.has("capabilities") && response.getAsJsonArray("capabilities")
                    .contains(new com.google.gson.JsonPrimitive("agent.layout_sketch.v1"));
            sessionId = response.get("session_id").getAsString();
            projectId = response.has("project_id") ? response.get("project_id").getAsString() : "";
            conversationId = response.has("conversation_id")
                    ? response.get("conversation_id").getAsString() : "";
            synchronized (sharedHistory) {
                sharedHistory.clear();
                sharedEventCursor = 0L;
            }
            activeWorldId = "";
            lastUploadedBookRevision = "";
            revision = 0;
            activeDiscovery = discovery;
            LOGGER.info("AutoFTBQ Studio bridge connected: project={}", projectId);
        }
        return discovery;
    }

    private JsonObject captureContext(int contextRevision) throws Exception {
        ServerSecurityState security = GamePlatform.serverGateway().probeServer()
                .get(5, TimeUnit.SECONDS);
        return Minecraft.getInstance().submit(
                () -> FTBQ2001ContextAdapter.capture(sessionId, contextRevision, security)
        ).get(5, TimeUnit.SECONDS);
    }

    private JsonObject captureSynchronizedContext(BridgeDiscovery discovery,
                                                  long timeoutMillis) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMillis);
        boolean postedInitialContext = false;
        int postedContextRevision = -1;
        String lastClientRevision = "";
        String lastServerRevision = "";
        while (true) {
            JsonObject context = captureContext(++revision);
            updateActiveWorld(context);
            String clientRevision = stringValue(context, "book_revision");
            String serverRevision = stringValue(context, "server_book_revision");
            lastClientRevision = clientRevision;
            lastServerRevision = serverRevision;
            if (!postedInitialContext) {
                applyContextIdentity(post(discovery, "/v1/context", context));
                postedInitialContext = true;
                postedContextRevision = context.get("revision").getAsInt();
            }
            if (isUsableRevision(clientRevision) && clientRevision.equals(serverRevision)) {
                if (postedContextRevision != context.get("revision").getAsInt()) {
                    applyContextIdentity(post(discovery, "/v1/context", context));
                }
                return context;
            }
            if (System.nanoTime() >= deadline) {
                LOGGER.warn("FTBQ preflight revision mismatch: client={} server={}",
                        shortRevision(lastClientRevision), shortRevision(lastServerRevision));
                throw new IllegalStateException(
                        "任务书同步校验失败（客户端 " + shortRevision(lastClientRevision)
                                + " / 服务器 " + shortRevision(lastServerRevision) + "）");
            }
            setStatus("正在等待客户端与服务器任务书同步…");
            Thread.sleep(400L);
        }
    }

    private void applyContextIdentity(JsonObject response) {
        if (response == null) return;
        if (response.has("project_id")) projectId = response.get("project_id").getAsString();
        if (response.has("conversation_id")) {
            conversationId = response.get("conversation_id").getAsString();
        }
    }

    private void pollRequest(BridgeDiscovery discovery, String currentRequestId,
                             String submittedPrompt) throws Exception {
        long nextContextSync = 0;
        while (currentRequestId.equals(requestId)) {
            if (System.nanoTime() >= nextContextSync) {
                JsonObject liveContext = captureContext(++revision);
                applyContextIdentity(post(discovery, "/v1/context", liveContext));
                uploadBookSnapshotIfChanged(discovery, liveContext);
                nextContextSync = System.nanoTime() + TimeUnit.SECONDS.toNanos(2);
            }
            processNextGameQuery(discovery);
            processNextStudioTransaction(discovery);
            JsonObject state = get(discovery, "/v1/requests/" + currentRequestId);
            String requestStatus = state.get("status").getAsString();
            pauseRequested = state.has("pause_requested") && state.get("pause_requested").getAsBoolean();
            JsonObject progress = state.getAsJsonObject("progress");
            if ("completed".equals(requestStatus)) {
                String completedResult = state.get("result").getAsString();
                String completedProposalId = state.has("proposal_id")
                        ? state.get("proposal_id").getAsString() : "";
                String completedPreview = "";
                if (!completedProposalId.isBlank()) {
                    JsonObject proposal = get(discovery, "/v1/proposals/" + completedProposalId);
                    proposalId = completedProposalId;
                    proposalPending = "proposed".equals(proposal.get("status").getAsString());
                    proposalOperationsJson = GSON.toJson(proposal.get("operations"));
                    proposalAffectedQuestIds = collectAffectedQuestIds(
                            proposal.getAsJsonArray("operations"));
                    proposalBaseServerRevision = proposal.get(
                            "base_server_book_revision").getAsString();
                    proposalAgentResult = completedResult;
                    completedPreview = formatProposalPreview(
                            proposal.get("summary").getAsString(),
                            proposal.getAsJsonArray("operations"));
                    setProposalPreview(completedPreview);
                    setStatus("修改事务已生成 · 正在自动提交服务器");
                } else {
                    String outcome = state.has("outcome")
                            ? state.get("outcome").getAsString() : "analysis_only";
                    setStatus("applied".equals(outcome) ? "任务完成 · 服务器已确认修改"
                            : "needs_attention".equals(outcome) ? "尚有未完成工作 · 检查点已保存"
                            : "generation_exhausted".equals(outcome)
                            ? "事务生成预算耗尽 · 任务书未修改"
                            : ("no_changes".equals(outcome)
                            ? "未生成修改事务 · 任务书未修改"
                            : "检查完成 · 未修改任务书"));
                }
                String displayedResult = completedProposalId.isBlank()
                        ? completedResult
                        : "【尚未修改】事务正在提交服务器。\n\n" + completedResult;
                setResult(displayedResult);
                history.add(new HistoryEntry(
                        submittedPrompt,
                        completedPreview.isBlank() ? displayedResult
                                : displayedResult + "\n\n" + completedPreview));
                return;
            }
            if ("failed".equals(requestStatus)) {
                setStatus("Agent 失败：" + state.get("error").getAsString());
                return;
            }
            if ("cancelled".equals(requestStatus)) {
                setStatus("请求已取消");
                return;
            }
            setStatus(pauseRequested && !"paused".equals(progress.get("stage").getAsString())
                    ? "正在暂停 · 等待当前步骤结束" : progress.get("message").getAsString());
            Thread.sleep(350);
        }
    }

    public void decideProposal(boolean confirm) {
        decideProposal(confirm, false);
    }

    private boolean decideProposal(boolean confirm, boolean alreadyOwnsFlight) {
        String currentProposalId = proposalId;
        BridgeDiscovery discovery = activeDiscovery;
        if (!proposalPending || currentProposalId.isBlank() || discovery == null
                || (!alreadyOwnsFlight && !inFlight.compareAndSet(false, true))) {
            return false;
        }
        proposalPending = false;
        setStatus(confirm ? "正在批准提案…" : "正在拒绝提案…");
        CompletableFuture.runAsync(() -> {
            try {
                JsonObject context = captureContext(++revision);
                applyContextIdentity(post(discovery, "/v1/context", context));
                JsonObject payload = new JsonObject();
                payload.addProperty("session_id", sessionId);
                payload.addProperty("context_revision", revision);
                payload.addProperty("book_revision", context.get("book_revision").getAsString());
                post(discovery, "/v1/proposals/" + currentProposalId
                        + (confirm ? "/confirm" : "/reject"), payload);
                if (!confirm) {
                    proposalAffectedQuestIds = Set.of();
                    setStatus("提案已拒绝 · 未修改任务书");
                    return;
                }
                setStatus("提案已批准 · 正在等待游戏服务器提交事务…");
                ProposalApplicationResult applied;
                try {
                    applied = applyProposalWithRetry(currentProposalId,
                            proposalBaseServerRevision, proposalOperationsJson);
                } catch (Exception error) {
                    setStatus("服务器事务结果未知，请勿重复提交：" + safeMessage(error));
                    updateTransactionResult("【状态未知】服务器没有返回可确认的应用结果，"
                            + "不能声称修改已经生效。请勿重复提交。\n\n" + proposalAgentResult);
                    return;
                }
                if (applied.success()) {
                    undoProposalId = currentProposalId;
                    undoBookRevision = applied.bookRevision();
                    undoAvailable = true;
                    setProposalPreview(proposalPreview.replace(
                            "修改记录（正在自动提交）", "修改记录（服务器已应用）"));
                    proposalAffectedQuestIds = Set.of();
                }
                JsonObject application = new JsonObject();
                application.addProperty("session_id", sessionId);
                application.addProperty("status", applied.status());
                application.addProperty("message", applied.message());
                application.addProperty("server_book_revision", applied.bookRevision());
                application.add("id_map", GSON.fromJson(applied.idMapJson(), JsonObject.class));
                boolean reported = reportApplication(discovery, currentProposalId, application);
                String reportWarning = reported ? "" : " · Studio 状态待恢复连接后同步";
                if (applied.success()) {
                    try {
                        JsonObject refreshed = captureContext(++revision);
                        applyContextIdentity(post(discovery, "/v1/context", refreshed));
                        uploadBookSnapshotIfChanged(discovery, refreshed);
                        syncSharedTimeline(discovery);
                        FTBQ2001ContextAdapter.refreshEmbeddedEditor();
                    } catch (Exception error) {
                        reportWarning += " · 上下文刷新失败";
                    }
                    setStatus("服务器已提交全部修改" + reportWarning);
                    updateTransactionResult("【修改已生效】游戏服务器已应用事务。\n\n"
                            + proposalAgentResult);
                } else if ("conflict".equals(applied.status())) {
                    setStatus("写入冲突：" + applied.message());
                    updateTransactionResult("【未修改】写入发生冲突：" + applied.message()
                            + "\n\n" + proposalAgentResult);
                } else {
                    setStatus("写入失败：" + applied.message());
                    updateTransactionResult("【未修改】服务器拒绝了事务：" + applied.message()
                            + "\n\n" + proposalAgentResult);
                }
            } catch (Exception error) {
                setStatus("提案操作失败：" + safeMessage(error));
                updateTransactionResult("【未修改】提案操作失败：" + safeMessage(error)
                        + "\n\n" + proposalAgentResult);
            } finally {
                inFlight.set(false);
            }
        });
        return true;
    }

    public void undoLastProposal() {
        String currentProposalId = undoProposalId;
        String expectedRevision = undoBookRevision;
        BridgeDiscovery discovery = activeDiscovery;
        if (!undoAvailable || currentProposalId.isBlank() || discovery == null
                || !inFlight.compareAndSet(false, true)) {
            return;
        }
        undoAvailable = false;
        setStatus("正在请求服务器撤销上次事务…");
        CompletableFuture.runAsync(() -> {
            try {
                ProposalUndoResult undone = undoProposalWithRetry(
                        currentProposalId, expectedRevision);
                if (!undone.success()) {
                    undoAvailable = true;
                    setStatus("撤销失败：" + undone.message());
                    updateTransactionResult("【撤回失败】服务器未能撤回修改：" + undone.message()
                            + "\n\n" + proposalAgentResult);
                    return;
                }
                setProposalPreview(proposalPreview.replace(
                        "修改记录（服务器已应用）", "修改记录（已撤回）"));
                updateTransactionResult("【修改已撤回】服务器已恢复到事务执行前的任务书。\n\n"
                        + proposalAgentResult);
                proposalAffectedQuestIds = Set.of();
                JsonObject application = new JsonObject();
                application.addProperty("session_id", sessionId);
                application.addProperty("status", "undone");
                application.addProperty("message", undone.message());
                application.addProperty("server_book_revision", undone.bookRevision());
                application.add("id_map", new JsonObject());
                boolean reported = reportApplication(discovery, currentProposalId, application);
                String reportWarning = reported ? "" : " · Studio 状态待恢复连接后同步";
                try {
                    JsonObject refreshed = captureContext(++revision);
                    applyContextIdentity(post(discovery, "/v1/context", refreshed));
                    uploadBookSnapshotIfChanged(discovery, refreshed);
                    syncSharedTimeline(discovery);
                    FTBQ2001ContextAdapter.refreshEmbeddedEditor();
                } catch (Exception error) {
                    reportWarning += " · 上下文刷新失败";
                }
                setStatus("已撤销上次服务器事务" + reportWarning);
            } catch (Exception error) {
                undoAvailable = true;
                setStatus("撤销失败：" + safeMessage(error));
                updateTransactionResult("【撤回状态未知】未收到服务器的成功回执，请检查任务书后再操作。"
                        + "\n\n" + proposalAgentResult);
            } finally {
                inFlight.set(false);
            }
        });
    }

    private void updateTransactionResult(String text) {
        setResult(text);
        String prompt = activePrompt;
        if (prompt.isBlank() || history.isEmpty()) return;
        for (int index = history.size() - 1; index >= 0; index--) {
            HistoryEntry entry = history.get(index);
            if (prompt.equals(entry.prompt())) {
                history.set(index, new HistoryEntry(prompt, text));
                return;
            }
        }
    }

    private void processNextGameQuery(BridgeDiscovery discovery) throws Exception {
        JsonObject response = get(
                discovery, "/v1/game-queries/next?session_id=" + sessionId
        );
        if (!response.has("query") || response.get("query").isJsonNull()) {
            return;
        }
        JsonObject query = response.getAsJsonObject("query");
        String queryId = query.get("query_id").getAsString();
        String name = query.get("name").getAsString();
        JsonObject arguments = query.getAsJsonObject("arguments");
        JsonObject queryResult = "inspect_game_data".equals(name)
                && arguments.has("kind") && "server_resource".equals(arguments.get("kind").getAsString())
                ? GSON.fromJson(dev.autoftbq.agent.forge.network.ForgeAgentNetwork
                    .queryData(GSON.toJson(arguments)).get(6, TimeUnit.SECONDS), JsonObject.class)
                : Minecraft.getInstance().submit(
                () -> FTBQ2001QueryExecutor.execute(name, arguments)
        ).get(5, TimeUnit.SECONDS);
        JsonObject payload = new JsonObject();
        payload.addProperty("session_id", sessionId);
        payload.add("result", queryResult);
        post(discovery, "/v1/game-queries/" + queryId + "/result", payload);
    }

    private static JsonObject createHandshake() {
        JsonObject value = new JsonObject();
        value.addProperty("protocol_version", 1);
        value.addProperty("client_id", CLIENT_ID);
        value.addProperty("minecraft_version", "1.20.1");
        JsonObject loader = new JsonObject();
        loader.addProperty("name", "forge");
        loader.addProperty("version", ForgeVersion.getVersion());
        value.add("loader", loader);
        value.addProperty("ftb_quests_version", modVersion("ftbquests"));
        value.addProperty("mod_version", modVersion("autoftbq_agent"));
        JsonArray capabilities = new JsonArray();
        capabilities.add("context.chapter");
        capabilities.add("context.selected_chapters");
        capabilities.add("context.selected_quests");
        capabilities.add("context.agent_selection.v1");
        capabilities.add("scope.enforced.v1");
        capabilities.add("request.preflight_sync.v1");
        capabilities.add("request.generation_recovery.v1");
        capabilities.add("agent.shared_core.v1");
        capabilities.add("data.evidence.v1");
        capabilities.add("transaction.strict_snbt.v1");
        capabilities.add("transaction.batch_index.v1");
        capabilities.add("agent.live_steps.v1");
        capabilities.add("result.server_truth.v1");
        capabilities.add("revision.network_fingerprint.v1");
        capabilities.add("context.registry_summary");
        capabilities.add("agent.transactional_edit");
        capabilities.add("agent.cancel");
        capabilities.add("game_query.selected_quest_details");
        capabilities.add("game_query.registry_search");
        capabilities.add("game_query.registry_batch");
        capabilities.add("game_query.registry_validate");
        capabilities.add("game_query.recipe_search");
        capabilities.add("proposal.preview");
        capabilities.add("proposal.decision");
        capabilities.add("conflict.book_revision");
        capabilities.add("security.server_authoritative");
        capabilities.add("write.transaction.v1");
        capabilities.add("application.recovery.v1");
        capabilities.add("project.timeline.v1");
        capabilities.add("project.snapshot.v1");
        capabilities.add("write.auto_apply.v1");
        value.add("capabilities", capabilities);
        return value;
    }

    private boolean reportApplication(BridgeDiscovery discovery, String currentProposalId,
                                      JsonObject application) {
        PendingApplicationReport report = new PendingApplicationReport(
                discovery, "/v1/proposals/" + currentProposalId + "/application",
                application.deepCopy());
        synchronized (pendingReports) {
            pendingReports.addLast(report);
        }
        try {
            flushPendingReports();
        } catch (Exception ignored) {
            return false;
        }
        synchronized (pendingReports) {
            return !pendingReports.contains(report);
        }
    }

    private ProposalApplicationResult applyProposalWithRetry(
            String currentProposalId, String expectedRevision,
            String operationsJson) throws Exception {
        Exception firstFailure = null;
        for (int attempt = 0; attempt < 2; attempt++) {
            try {
                return GamePlatform.serverGateway().applyProposal(
                        currentProposalId, expectedRevision, operationsJson)
                        .get(17, TimeUnit.SECONDS);
            } catch (Exception error) {
                firstFailure = error;
            }
        }
        throw firstFailure;
    }

    private ProposalUndoResult undoProposalWithRetry(
            String currentProposalId, String expectedRevision) throws Exception {
        Exception firstFailure = null;
        for (int attempt = 0; attempt < 2; attempt++) {
            try {
                return GamePlatform.serverGateway().undoProposal(
                        currentProposalId, expectedRevision).get(17, TimeUnit.SECONDS);
            } catch (Exception error) {
                firstFailure = error;
            }
        }
        throw firstFailure;
    }

    private void flushPendingReportsQuietly() {
        try {
            flushPendingReports();
        } catch (Exception ignored) {
            // The queue intentionally survives transient Studio disconnects.
        }
    }

    private void flushPendingReports() throws Exception {
        synchronized (pendingReports) {
            while (!pendingReports.isEmpty()) {
                PendingApplicationReport report = pendingReports.peekFirst();
                post(report.discovery(), report.path(), report.payload());
                pendingReports.removeFirst();
            }
        }
    }

    private static String modVersion(String modId) {
        return ModList.get().getModContainerById(modId)
                .map(container -> container.getModInfo().getVersion().toString())
                .orElse("unknown");
    }

    private static Set<String> collectAffectedQuestIds(JsonArray operations) {
        Set<String> result = new HashSet<>();
        if (operations == null) return Set.of();
        for (var element : operations) {
            if (!element.isJsonObject()) continue;
            JsonObject operation = element.getAsJsonObject();
            for (String key : List.of("quest_id", "dependency_id")) {
                if (!operation.has(key) || !operation.get(key).isJsonPrimitive()) continue;
                String id = operation.get(key).getAsString().trim();
                if (id.matches("(?i)[0-9a-f]{1,16}")) result.add(id.toUpperCase());
            }
        }
        return Set.copyOf(result);
    }

    private static String formatProposalPreview(String summary, JsonArray operations) {
        StringBuilder text = new StringBuilder("修改记录（正在自动提交）\n")
                .append(summary).append("\n共 ").append(operations.size()).append(" 项修改：");
        int number = 1;
        for (var element : operations) {
            if (!element.isJsonObject()) continue;
            JsonObject operation = element.getAsJsonObject();
            String kind = stringValue(operation, "kind");
            text.append("\n").append(number++).append(". ");
            switch (kind) {
                case "create_chapter" -> text.append("新建章节「")
                        .append(stringValue(operation, "title")).append("」")
                        .append(reference(operation, "temp_id"));
                case "create_quest" -> text.append("新建任务「")
                        .append(stringValue(operation, "title")).append("」")
                        .append(reference(operation, "temp_id"))
                        .append("，章节 ").append(stringValue(operation, "chapter_id"))
                        .append("，位置 (").append(stringValue(operation, "x"))
                        .append(", ").append(stringValue(operation, "y")).append(")");
                case "update_quest" -> text.append("更新任务 ")
                        .append(stringValue(operation, "quest_id")).append("：")
                        .append(operation.has("changes")
                                ? PRETTY_GSON.toJson(operation.get("changes")).replace("\n", " ")
                                : "无字段");
                case "add_dependency" -> text.append("任务 ")
                        .append(stringValue(operation, "quest_id")).append(" 添加前置 ")
                        .append(stringValue(operation, "dependency_id"));
                case "add_item_task" -> text.append("任务 ")
                        .append(stringValue(operation, "quest_id")).append(" 添加物品目标 ")
                        .append(stringValue(operation, "item_id")).append(" ×")
                        .append(stringValue(operation, "count"));
                case "add_item_reward" -> text.append("任务 ")
                        .append(stringValue(operation, "quest_id")).append(" 添加物品奖励 ")
                        .append(stringValue(operation, "item_id")).append(" ×")
                        .append(stringValue(operation, "count"));
                case "add_checkmark_task" -> text.append("任务 ")
                        .append(stringValue(operation, "quest_id")).append(" 添加勾选目标");
                case "add_xp_task" -> text.append("任务 ")
                        .append(stringValue(operation, "quest_id")).append(" 添加经验目标 ")
                        .append(stringValue(operation, "amount"));
                case "add_xp_reward" -> text.append("任务 ")
                        .append(stringValue(operation, "quest_id")).append(" 添加经验奖励 ")
                        .append(stringValue(operation, "amount"));
                case "add_xp_levels_reward" -> text.append("任务 ")
                        .append(stringValue(operation, "quest_id")).append(" 添加等级奖励 ")
                        .append(stringValue(operation, "amount"));
                default -> text.append(kind.isBlank() ? "未知修改" : kind)
                        .append("：").append(GSON.toJson(operation));
            }
        }
        text.append("\n\n修改通过校验后会自动写入服务器，并保留撤回快照。");
        return text.toString();
    }

    private void uploadBookSnapshotIfChanged(BridgeDiscovery discovery,
                                             JsonObject context) throws Exception {
        String bookRevision = context.has("book_revision")
                ? context.get("book_revision").getAsString() : "";
        if (bookRevision.isBlank() || bookRevision.equals(lastUploadedBookRevision)) return;
        JsonObject snapshot = Minecraft.getInstance().submit(
                FTBQ2001ContextAdapter::captureBookSnapshot
        ).get(8, TimeUnit.SECONDS);
        JsonObject payload = new JsonObject();
        payload.addProperty("session_id", sessionId);
        payload.addProperty("book_revision", bookRevision);
        payload.addProperty("format", "ftbquests-snbt-v1");
        payload.add("snapshot", snapshot);
        post(discovery, "/v1/project/snapshot", payload);
        lastUploadedBookRevision = bookRevision;
        LOGGER.info("AutoFTBQ task-book snapshot uploaded: revision={}", bookRevision);
    }

    private void updateActiveWorld(JsonObject context) {
        String worldId = stringValue(context, "world_id");
        if (!worldId.equals(activeWorldId)) {
            AgentContextSelection.clear();
            synchronized (sharedHistory) {
                sharedHistory.clear();
            }
            sharedEventCursor = 0L;
            history.clear();
            historyIndex = -1;
            projectId = "";
            conversationId = "";
            proposalId = "";
            proposalPreview = "";
            proposalPending = false;
            proposalAffectedQuestIds = Set.of();
            undoAvailable = false;
            undoProposalId = "";
            undoBookRevision = "";
            activeWorldId = worldId;
            lastUploadedBookRevision = "";
        }
    }

    private void syncSharedTimeline(BridgeDiscovery discovery) throws Exception {
        boolean changed = false;
        for (int page = 0; page < 10; page++) {
            JsonObject envelope = get(discovery,
                    "/v1/events?session_id=" + sessionId + "&after=" + sharedEventCursor
                            + "&limit=500");
            JsonArray events = envelope.getAsJsonArray("events");
            if (events == null || events.isEmpty()) break;
            for (var element : events) {
                if (!element.isJsonObject()) continue;
                JsonObject event = element.getAsJsonObject();
                if (event.has("event_id")) {
                    sharedEventCursor = Math.max(
                            sharedEventCursor, event.get("event_id").getAsLong());
                }
                String kind = stringValue(event, "kind");
                if (!event.has("payload") || !event.get("payload").isJsonObject()) continue;
                JsonObject payload = event.getAsJsonObject("payload");
                if (!payload.has("request_id")) continue;
                String id = payload.get("request_id").getAsString();
                String[] pair;
                synchronized (sharedHistory) {
                    pair = sharedHistory.computeIfAbsent(id, ignored -> new String[]{"", ""});
                }
                if ("chat.user".equals(kind)) pair[0] = stringValue(payload, "text");
                if ("chat.assistant".equals(kind)) pair[1] = stringValue(payload, "text");
                if ("change.applied".equals(kind)) {
                    pair[1] = transactionHistoryText("【修改已生效】", payload, pair[1]);
                } else if ("change.failed".equals(kind)) {
                    pair[1] = transactionHistoryText("【未修改】", payload, pair[1]);
                } else if ("change.conflict".equals(kind)) {
                    pair[1] = transactionHistoryText("【写入冲突 · 未修改】", payload, pair[1]);
                } else if ("change.undone".equals(kind)) {
                    pair[1] = transactionHistoryText("【修改已撤回】", payload, pair[1]);
                }
                changed = true;
            }
            if (events.size() < 500) break;
        }
        if (!changed) return;
        history.clear();
        synchronized (sharedHistory) {
            while (sharedHistory.size() > 300) {
                sharedHistory.remove(sharedHistory.keySet().iterator().next());
            }
            for (String[] pair : sharedHistory.values()) {
                if (!pair[0].isBlank() && !pair[1].isBlank()) {
                    history.add(new HistoryEntry(pair[0], pair[1]));
                }
            }
        }
    }

    private static String loadPersistentClientId() {
        Path path = Path.of(System.getProperty("user.home"), ".autoftbq", "client-id.txt");
        try {
            Files.createDirectories(path.getParent());
            if (Files.isRegularFile(path)) {
                String existing = Files.readString(path, StandardCharsets.UTF_8).trim();
                if (!existing.isBlank() && existing.length() <= 100) return existing;
            }
            String generated = UUID.randomUUID().toString();
            Files.writeString(path, generated, StandardCharsets.UTF_8);
            return generated;
        } catch (Exception ignored) {
            return UUID.randomUUID().toString();
        }
    }

    private static String reference(JsonObject value, String key) {
        String reference = stringValue(value, key);
        return reference.isBlank() ? "" : " [" + reference + "]";
    }

    private static String stringValue(JsonObject value, String key) {
        if (!value.has(key) || value.get(key).isJsonNull()) return "";
        return value.get(key).isJsonPrimitive()
                ? value.get(key).getAsString() : GSON.toJson(value.get(key));
    }

    private static boolean isUsableRevision(String value) {
        return value != null && value.matches("(?i)[0-9a-f]{64}");
    }

    private static String shortRevision(String value) {
        if (value == null || value.isBlank()) return "缺失";
        if ("unavailable".equalsIgnoreCase(value)) return "不可用";
        return value.length() <= 12 ? value : value.substring(0, 12);
    }

    private static String transactionHistoryText(String label, JsonObject payload,
                                                 String previous) {
        String message = stringValue(payload, "message");
        String header = message.isBlank() ? label : label + " " + message;
        if (previous == null || previous.isBlank()) return header;
        String clean = previous;
        if (clean.startsWith("【")) {
            int paragraph = clean.indexOf("\n\n");
            clean = paragraph >= 0 ? clean.substring(paragraph + 2) : "";
        }
        return clean.isBlank() ? header : header + "\n\n" + clean;
    }

    private JsonObject post(BridgeDiscovery discovery, String path, JsonObject payload) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create(discovery.endpoint(path)))
                .timeout(Duration.ofSeconds(20))
                .header("Authorization", "Bearer " + discovery.token())
                .header("Content-Type", "application/json; charset=utf-8")
                .POST(HttpRequest.BodyPublishers.ofString(GSON.toJson(payload)))
                .build();
        HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200) {
            throw studioError(response);
        }
        return GSON.fromJson(response.body(), JsonObject.class);
    }

    private JsonObject get(BridgeDiscovery discovery, String path) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create(discovery.endpoint(path)))
                .timeout(Duration.ofSeconds(5))
                .header("Authorization", "Bearer " + discovery.token())
                .GET()
                .build();
        HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200) {
            throw studioError(response);
        }
        return GSON.fromJson(response.body(), JsonObject.class);
    }

    private static IllegalStateException studioError(HttpResponse<String> response) {
        String detail = "";
        try {
            JsonObject body = GSON.fromJson(response.body(), JsonObject.class);
            if (body != null && body.has("message")) detail = body.get("message").getAsString();
            else if (body != null && body.has("error")) detail = body.get("error").getAsString();
        } catch (RuntimeException ignored) {
        }
        return new IllegalStateException("Studio 返回 HTTP " + response.statusCode()
                + (detail.isBlank() ? "" : "：" + detail));
    }

    private void setStatus(String value) {
        Minecraft.getInstance().execute(() -> status = value);
    }

    private void setResult(String value) {
        Minecraft.getInstance().execute(() -> result = value);
    }

    private void setProposalPreview(String value) {
        Minecraft.getInstance().execute(() -> proposalPreview = value);
    }

    private static String safeMessage(Exception error) {
        String message = error.getMessage();
        return message == null || message.isBlank() ? error.getClass().getSimpleName() : message;
    }

    private record HistoryEntry(String prompt, String text) {
    }

    private record PendingApplicationReport(BridgeDiscovery discovery, String path,
                                            JsonObject payload) {
    }
}
