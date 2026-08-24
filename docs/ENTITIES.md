# Карта сущностей проекта

Сгенерировано `forge map` (AST-скан, без LLM). Перегенерация после каждого
принятого прогона. Машиночитаемая версия — `canon/entities.json` (read-only
для агентов). При доработке модуля модель получает из этой карты сигнатуры
связанных сущностей — не открывая несвязанные файлы.

Файлов: 41 · публичных сущностей: 213

## `forge/`

### `forge/__init__.py`

### `forge/__main__.py`
- локальные импорты: `forge/cli.py`

### `forge/agents.py`
- `class AgentOutcome` (строка 23)
- `def parse_marker(content: str) -> str | None` (строка 28)
- `def log_model_call(journal: Journal, cfg: ForgeConfig, task_id: str | None, phase: str, role: str, result: ChatResult) -> float` (строка 40)
- `def run_tool_agent(client: LLMClient, cfg: ForgeConfig, journal: Journal, *, role: str, system_prompt: str, user_prompt: str, toolbox: ToolBox, task_id: str, phase: str, max_steps: int=MAX_AGENT_STEPS, history_path: Path | None=None) -> AgentOutcome` (строка 79)
- `def run_reviewer(client: LLMClient, cfg: ForgeConfig, journal: Journal, *, system_prompt: str, review_prompt: str, task_id: str) -> str` (строка 171)
- `def parse_verdict(review_text: str) -> str` (строка 191)
- локальные импорты: `forge/config.py`, `forge/journal.py`, `forge/llm.py`, `forge/tools.py`

### `forge/cli.py`
- `def cmd_run(args: argparse.Namespace) -> int` (строка 36)
- `def cmd_resume(args: argparse.Namespace) -> int` (строка 51)
- `def cmd_status(args: argparse.Namespace) -> int` (строка 65)
- `def cmd_log(args: argparse.Namespace) -> int` (строка 72)
- `def cmd_report(args: argparse.Namespace) -> int` (строка 96)
- `def cmd_init(args: argparse.Namespace) -> int` (строка 107)
- `def cmd_wizard(args: argparse.Namespace) -> int` (строка 117)
- `def cmd_lint(args: argparse.Namespace) -> int` (строка 144)
- `def cmd_map(args: argparse.Namespace) -> int` (строка 152)
- `def cmd_accept(args: argparse.Namespace) -> int` (строка 165)
- `def cmd_ui(args: argparse.Namespace) -> int` (строка 175)
- `def cmd_import(args: argparse.Namespace) -> int` (строка 181)
- `def build_parser() -> argparse.ArgumentParser` (строка 213)
- `def main(argv: list[str] | None=None) -> int` (строка 304)
- локальные импорты: `forge/agents.py`, `forge/config.py`, `forge/dryrun.py`, `forge/init.py`, `forge/journal.py`, `forge/lint.py`, `forge/llm.py`, `forge/map.py`, `forge/prompts.py`, `forge/report.py`, `forge/runner.py`, `forge/ui.py`, `forge/wizard.py`

### `forge/config.py`
- `class RoleConfig: cost_usd` (строка 20)
- `class Budgets` (строка 35)
- `class RetryConfig` (строка 43)
- `class ForgeConfig: role` (строка 49)
- `def forge_root() -> Path` (строка 65)
- `def load_env_file(root: Path) -> dict[str, str]` (строка 73)
- `def load_config(root: Path | None=None, provider_path: Path | None=None) -> ForgeConfig` (строка 97)

### `forge/detect.py`
- `class RepoScan` (строка 27)
- `class BaselineResult` (строка 39)
- `def scan_repo(root: Path) -> RepoScan` (строка 106)
- `def run_baseline(root: Path, commands: list[str], timeout: int=300) -> list[BaselineResult]` (строка 122)
- `def render_scan(scan: RepoScan) -> str` (строка 139)
- `def render_baseline(results: list[BaselineResult]) -> str` (строка 154)

### `forge/dryrun.py`
- `def dry_run_report(tasks_path: Path, runs_dir: Path, per_run_cap: float) -> str` (строка 38)
- локальные импорты: `forge/models.py`

### `forge/init.py`
- `def init_project(target: Path, forge_root: Path, profile_name: str=DEFAULT_PROFILE, force: bool=False, check: bool=True) -> str` (строка 97)
- `def env_has_api_key(forge_root: Path) -> bool` (строка 132)
- локальные импорты: `forge/detect.py`, `forge/profiles.py`

### `forge/journal.py`
- `def utc_now() -> str` (строка 20)
- `def new_run_id() -> str` (строка 24)
- `class Journal: write_meta, read_meta, accept_task, accepted_tasks, event, read_events, task_state, set_task_state, log_for_task` (строка 28)
- локальные импорты: `forge/models.py`

### `forge/lint.py`
- `def is_test_command(command: str) -> bool` (строка 30)
- `def scope_covers_tests(task: dict[str, Any]) -> bool` (строка 35)
- `def acceptance_order_warnings(tasks: list[dict[str, Any]], *, existing_tests: bool | None=None) -> list[str]` (строка 66)
- `def has_existing_tests(root: Path) -> bool` (строка 98)
- `def test_scope_warnings(tasks: list[dict[str, Any]]) -> list[str]` (строка 112)
- `def lint_tasks(path: Path) -> tuple[list[str], list[str]]` (строка 129)
- `def render_lint(path: Path, errors: list[str], warnings: list[str]) -> str` (строка 161)
- локальные импорты: `forge/models.py`

### `forge/llm.py`
- `class ToolCall` (строка 21)
- `class ChatResult` (строка 28)
- `class LLMClient(Protocol): chat` (строка 36)
- `class ProviderError(Exception)` (строка 47)
- `class OpenAIClient: chat` (строка 51)
- `class MockClient: scenario, chat` (строка 167)
- `def make_client(cfg: ForgeConfig) -> LLMClient` (строка 302)
- локальные импорты: `forge/config.py`

### `forge/map.py`
- `class Entity` (строка 40)
- `class FileMap` (строка 50)
- `def scan_entities(root: Path) -> dict[str, FileMap]` (строка 121)
- `def write_map(root: Path, maps: dict[str, FileMap]) -> tuple[Path, Path]` (строка 149)
- `def render_entities_md(maps: dict[str, FileMap]) -> str` (строка 176)
- `def load_entity_index(root: Path) -> dict[str, object] | None` (строка 207)
- `def neighbors_of(scope: set[str], files: dict[str, object]) -> set[str]` (строка 230)
- `def build_repo_context(root: Path, scope_paths: list[str]) -> str` (строка 242)

### `forge/models.py`
- `class TaskBudget` (строка 19)
- `class Task` (строка 27)
- `class TaskPackage` (строка 39)
- `def load_tasks(path: Path) -> TaskPackage` (строка 47)
- `def topo_order(tasks: list[Task]) -> list[Task]` (строка 115)
- `class TaskState` (строка 134)

### `forge/profiles.py`
- `class Profile` (строка 14)
- `def get_profile(name: str) -> Profile` (строка 62)
- `def render_profiles() -> str` (строка 72)

### `forge/prompts.py`
- `def load_prompt(prompts_dir: Path, name: str) -> str` (строка 19)
- `def render(template: str, values: dict[str, str]) -> str` (строка 24)
- `def prompts_version(prompts_dir: Path) -> str` (строка 32)

### `forge/report.py`
- `class TaskReport` (строка 15)
- `class RunReport: total_cost, total_tokens` (строка 27)
- `def latest_run_id(runs_dir: Path) -> str | None` (строка 41)
- `def build_report(runs_dir: Path, run_id: str) -> RunReport` (строка 58)
- `def render_status(report: RunReport) -> str` (строка 119)
- `def render_report(report: RunReport, per_run_cap: float | None=None) -> str` (строка 142)
- `def render_plain(report: RunReport) -> str` (строка 161)
- локальные импорты: `forge/journal.py`, `forge/models.py`

### `forge/runner.py`
- `def run_shell(root: Path, command: str, timeout: int=ACCEPTANCE_TIMEOUT) -> tuple[int, str]` (строка 24)
- `class Runner: run, accept` (строка 40)
- локальные импорты: `forge/agents.py`, `forge/config.py`, `forge/journal.py`, `forge/llm.py`, `forge/map.py`, `forge/models.py`, `forge/prompts.py`, `forge/tools.py`

### `forge/tools.py`
- `def glob_to_regex(pattern: str) -> re.Pattern[str]` (строка 102)
- `def path_in_scope(rel_path: str, scope_patterns: list[str]) -> bool` (строка 119)
- `class ScopeViolation(Exception)` (строка 125)
- `class CommandNotAllowed(Exception)` (строка 129)
- `class ToolBox: call, check_write_allowed, read_file, write_file, list_dir, run_command` (строка 133)

### `forge/ui.py`
- `def list_runs(runs_dir: Path) -> list[dict[str, Any]]` (строка 69)
- `def run_detail(runs_dir: Path, run_id: str) -> dict[str, Any] | None` (строка 112)
- `def run_events(runs_dir: Path, run_id: str, task: str | None, tail: int) -> list[dict[str, Any]] | None` (строка 152)
- `def make_handler(runs_dir: Path) -> type[BaseHTTPRequestHandler]` (строка 321)
- `def create_server(runs_dir: Path, port: int=8765, host: str='127.0.0.1') -> ThreadingHTTPServer` (строка 407)
- `def serve(runs_dir: Path, port: int) -> int` (строка 412)
- локальные импорты: `forge/lint.py`, `forge/models.py`

### `forge/wizard.py`
- `def run_wizard(cfg: ForgeConfig, client: LLMClient, target: Path, intent: str, profile_name: str=DEFAULT_PROFILE, out: Path | None=None, force: bool=False, check: bool=True, ask: Callable[[str], str] | None=input) -> str` (строка 262)
- `def list_recipes(recipes_dir: Path) -> list[str]` (строка 373)
- `def run_recipe(cfg: ForgeConfig, target: Path, recipe_name: str, profile_name: str=DEFAULT_PROFILE, out: Path | None=None, force: bool=False, ask: Callable[[str], str] | None=input) -> str` (строка 378)
- локальные импорты: `forge/agents.py`, `forge/config.py`, `forge/detect.py`, `forge/journal.py`, `forge/lint.py`, `forge/llm.py`, `forge/models.py`, `forge/profiles.py`, `forge/prompts.py`


## `site/`

### `site/build_pages.py`
- `def main() -> int` (строка 32)


## `tests/`

### `tests/conftest.py`
- `def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ForgeConfig` (строка 17)
- `def target(tmp_path: Path) -> Path` (строка 28)
- `def runner(cfg: ForgeConfig, target: Path) -> Runner` (строка 36)
- `def write_tasks(tmp_path: Path, body: str) -> Path` (строка 40)
- локальные импорты: `forge/config.py`, `forge/llm.py`, `forge/runner.py`

### `tests/test_budget.py`
- `def test_per_task_cost_cap_blocks(tmp_path: Path, runner: Runner, cfg) -> None` (строка 13)
- `def test_per_run_cost_cap_blocks(tmp_path: Path, runner: Runner, cfg) -> None` (строка 24)
- `def test_per_day_cost_cap_blocks(tmp_path: Path, runner: Runner, cfg) -> None` (строка 32)
- локальные импорты: `forge/journal.py`, `forge/runner.py`, `tests/conftest.py`

### `tests/test_cli.py`
- `def test_planner_mock_draft_is_valid_yaml(cfg) -> None` (строка 9)
- `def test_cli_parser_commands() -> None` (строка 16)
- локальные импорты: `forge/cli.py`, `forge/llm.py`

### `tests/test_detect.py`
- `def test_detect_python_repo(tmp_path: Path) -> None` (строка 8)
- `def test_detect_node_repo(tmp_path: Path) -> None` (строка 16)
- `def test_detect_node_without_test_script(tmp_path: Path) -> None` (строка 25)
- `def test_detect_dotnet_and_git(tmp_path: Path) -> None` (строка 32)
- `def test_detect_ci_commands(tmp_path: Path) -> None` (строка 41)
- `def test_detect_empty_repo(tmp_path: Path) -> None` (строка 57)
- `def test_render_baseline_red_stops() -> None` (строка 63)
- `def test_render_scan_lists_commands(tmp_path: Path) -> None` (строка 72)
- локальные импорты: `forge/detect.py`

### `tests/test_dryrun.py`
- `def test_dry_run_caps_without_history(tmp_path: Path) -> None` (строка 25)
- `def test_dry_run_uses_history_median(tmp_path: Path) -> None` (строка 37)
- локальные импорты: `forge/dryrun.py`

### `tests/test_init.py`
- `def test_init_creates_skeleton_and_git(tmp_path: Path) -> None` (строка 10)
- `def test_init_does_not_overwrite_without_force(tmp_path: Path) -> None` (строка 21)
- `def test_init_warns_about_missing_env(tmp_path: Path) -> None` (строка 32)
- `def test_init_baseline_runs_detected_checks(tmp_path: Path) -> None` (строка 39)
- `def test_init_rejects_missing_dir(tmp_path: Path) -> None` (строка 48)
- локальные импорты: `forge/init.py`

### `tests/test_lint.py`
- `def test_lint_good_queue(tmp_path: Path) -> None` (строка 39)
- `def test_lint_catches_tests_in_scope(tmp_path: Path) -> None` (строка 47)
- `def test_lint_warns_on_missing_acceptance_and_budget(tmp_path: Path) -> None` (строка 55)
- `def test_lint_reports_contract_error(tmp_path: Path) -> None` (строка 64)
- `def test_lint_warns_on_test_acceptance_before_tests_exist(tmp_path: Path) -> None` (строка 110)
- `def test_lint_no_order_warning_when_tests_task_first(tmp_path: Path) -> None` (строка 122)
- `def test_has_existing_tests(tmp_path: Path) -> None` (строка 130)
- локальные импорты: `forge/lint.py`

### `tests/test_map.py`
- `def test_scan_entities_extracts_public_surface(tmp_path: Path) -> None` (строка 46)
- `def test_scan_resolves_local_imports(tmp_path: Path) -> None` (строка 61)
- `def test_write_map_creates_canon_and_docs(tmp_path: Path) -> None` (строка 69)
- `def test_neighbors_graph_both_directions(tmp_path: Path) -> None` (строка 80)
- `def test_repo_context_empty_without_artifacts(tmp_path: Path) -> None` (строка 90)
- `def test_repo_context_catalog_and_neighbors(tmp_path: Path) -> None` (строка 95)
- `def test_repo_context_agents_md(tmp_path: Path) -> None` (строка 109)
- локальные импорты: `forge/map.py`

### `tests/test_mock_run.py`
- `def test_mock_run_done(runner: Runner, cfg, target: Path, tmp_path: Path) -> None` (строка 12)
- `def test_scope_violation_logged(runner: Runner, cfg, tmp_path: Path, monkeypatch) -> None` (строка 36)
- `def test_gate_blocks_until_accept(runner: Runner, cfg, tmp_path: Path) -> None` (строка 49)
- `def test_accept_overrides_blocked(runner: Runner, cfg, tmp_path: Path) -> None` (строка 80)
- локальные импорты: `forge/journal.py`, `forge/report.py`, `forge/runner.py`, `tests/conftest.py`

### `tests/test_recipes.py`
- `def test_recipes_gallery_present(cfg) -> None` (строка 11)
- `def test_recipe_test_coverage_defaults(cfg, target: Path) -> None` (строка 16)
- `def test_recipe_feature_two_tasks_with_answers(cfg, target: Path) -> None` (строка 26)
- `def test_recipe_unknown_name_lists_available(cfg, target: Path) -> None` (строка 38)
- `def test_recipe_refuses_overwrite(cfg, target: Path) -> None` (строка 43)
- `def test_all_recipes_render_valid_dags(cfg, target: Path, tmp_path: Path) -> None` (строка 49)
- локальные импорты: `forge/models.py`, `forge/wizard.py`

### `tests/test_repair.py`
- `def test_repair_heals_within_limit(runner: Runner, cfg, tmp_path: Path) -> None` (строка 29)
- `def test_repair_exhausted_fails_with_journal(runner: Runner, cfg, tmp_path: Path) -> None` (строка 40)
- локальные импорты: `forge/journal.py`, `forge/runner.py`, `tests/conftest.py`

### `tests/test_report_gate.py`
- `def test_report_counts_queued_from_tasks_path(cfg, tmp_path: Path) -> None` (строка 53)
- `def test_report_without_tasks_path_keeps_old_behavior(cfg) -> None` (строка 63)
- `def test_status_shows_gate_wait_hint(cfg, tmp_path: Path) -> None` (строка 73)
- `def test_status_no_hint_after_accept(cfg, tmp_path: Path) -> None` (строка 81)
- `def test_runner_blocks_dependent_of_failed_dependency(cfg) -> None` (строка 88)
- локальные импорты: `forge/journal.py`, `forge/models.py`, `forge/report.py`, `forge/runner.py`, `tests/conftest.py`

### `tests/test_report_plain.py`
- `def test_plain_all_done(cfg) -> None` (строка 20)
- `def test_plain_failed_and_blocked(cfg) -> None` (строка 28)
- `def test_plain_empty_run(cfg) -> None` (строка 44)
- `def test_history_snapshots_are_not_task_states(cfg) -> None` (строка 50)
- локальные импорты: `forge/journal.py`, `forge/models.py`, `forge/report.py`, `forge/ui.py`

### `tests/test_resume_history.py`
- `class StubClient: chat` (строка 13)
- `def test_history_saved_and_resumed(cfg, target: Path, tmp_path: Path) -> None` (строка 29)
- `def test_history_dropped_on_steps_exhausted(cfg, target: Path, tmp_path: Path) -> None` (строка 63)
- локальные импорты: `forge/agents.py`, `forge/journal.py`, `forge/llm.py`, `forge/tools.py`

### `tests/test_scope.py`
- `def test_glob_patterns() -> None` (строка 11)
- `def test_glob_double_star_matches_nested() -> None` (строка 20)
- `def test_write_outside_scope_blocked(tmp_path: Path) -> None` (строка 25)
- `def test_write_into_canon_always_blocked(tmp_path: Path) -> None` (строка 33)
- `def test_path_traversal_blocked(tmp_path: Path) -> None` (строка 40)
- `def test_write_inside_scope_ok(tmp_path: Path) -> None` (строка 46)
- `def test_run_command_whitelist(tmp_path: Path) -> None` (строка 53)
- локальные импорты: `forge/config.py`, `forge/tools.py`

### `tests/test_tasks_model.py`
- `def test_example_tasks_parse() -> None` (строка 11)
- `def test_topo_order_respects_dependencies(tmp_path: Path) -> None` (строка 22)
- `def test_cycle_rejected(tmp_path: Path) -> None` (строка 32)
- `def test_duplicate_id_rejected(tmp_path: Path) -> None` (строка 42)
- `def test_unknown_dependency_rejected(tmp_path: Path) -> None` (строка 52)
- локальные импорты: `forge/models.py`, `tests/conftest.py`

### `tests/test_tools_policy.py`
- `def make_toolbox(target: Path) -> ToolBox` (строка 8)
- `def test_dotnet_allowed(target: Path) -> None` (строка 12)
- `def test_dependency_install_blocked(target: Path) -> None` (строка 19)
- `def test_innocent_commands_not_blocked(target: Path) -> None` (строка 38)
- локальные импорты: `forge/tools.py`

### `tests/test_ui.py`
- `def runs_dir(tmp_path: Path) -> Path` (строка 67)
- `def ui_server(runs_dir: Path) -> Iterator[str]` (строка 74)
- `def synthetic_run(runs_dir: Path, tmp_path: Path) -> str` (строка 88)
- `def test_runs_empty(runs_dir: Path, ui_server: str) -> None` (строка 126)
- `def test_index_served(ui_server: str) -> None` (строка 132)
- `def test_runs_summary(runs_dir: Path, ui_server: str, synthetic_run: str) -> None` (строка 139)
- `def test_run_detail_titles_and_totals(runs_dir: Path, ui_server: str, synthetic_run: str) -> None` (строка 155)
- `def test_run_detail_without_tasks_yaml(runs_dir: Path, ui_server: str, synthetic_run: str) -> None` (строка 174)
- `def test_events_tail_and_task_filter(runs_dir: Path, ui_server: str, synthetic_run: str) -> None` (строка 187)
- `def test_events_note_truncated(runs_dir: Path, ui_server: str, synthetic_run: str) -> None` (строка 197)
- `def test_unknown_run_404(runs_dir: Path, ui_server: str, synthetic_run: str) -> None` (строка 205)
- `def test_run_id_traversal_404(runs_dir: Path, ui_server: str, synthetic_run: str) -> None` (строка 213)
- локальные импорты: `forge/journal.py`, `forge/models.py`, `forge/ui.py`

### `tests/test_ui_wizard.py`
- `def draft_file(tmp_path: Path) -> Path` (строка 40)
- `def ui_server(tmp_path: Path) -> Iterator[str]` (строка 47)
- `def test_wizard_form_renders_cards(ui_server: str, draft_file: Path) -> None` (строка 80)
- `def test_wizard_form_requires_yaml(ui_server: str, tmp_path: Path) -> None` (строка 88)
- `def test_wizard_save_roundtrip(ui_server: str, draft_file: Path) -> None` (строка 97)
- `def test_wizard_save_rejects_invalid_without_touching_file(ui_server: str, draft_file: Path) -> None` (строка 119)
- `def test_wizard_save_bad_cost(ui_server: str, draft_file: Path) -> None` (строка 136)
- `def test_wizard_api_still_json_404(ui_server: str) -> None` (строка 147)
- локальные импорты: `forge/models.py`, `forge/ui.py`

### `tests/test_wizard.py`
- `def test_wizard_writes_valid_draft(cfg, target: Path) -> None` (строка 15)
- `def test_wizard_refuses_overwrite_without_force(cfg, target: Path) -> None` (строка 28)
- `def test_wizard_normal_profile_no_gate_per_task(cfg, target: Path) -> None` (строка 35)
- `def test_wizard_logs_planner_call(cfg, target: Path) -> None` (строка 41)
- `def test_normalize_fills_acceptance_from_scan() -> None` (строка 50)
- `def test_normalize_strips_test_acceptance_before_tests_exist() -> None` (строка 58)
- `def test_normalize_keeps_test_acceptance_when_repo_has_tests() -> None` (строка 76)
- `def test_normalize_warns_on_empty_acceptance_without_scan() -> None` (строка 84)
- `def test_test_scope_warnings() -> None` (строка 91)
- `def test_wizard_survives_non_yaml_planner_reply(cfg, target: Path, monkeypatch) -> None` (строка 98)
- `def test_wizard_draft_parses_with_yaml_directly(cfg, target: Path) -> None` (строка 115)
- `def test_wizard_interview_asks_and_continues(cfg, target: Path, monkeypatch) -> None` (строка 124)
- `def test_wizard_interview_noninteractive_warns(cfg, target: Path, monkeypatch) -> None` (строка 135)
- `def test_strip_fences() -> None` (строка 146)
- `def test_wizard_repairs_fenced_yaml(cfg, target: Path) -> None` (строка 154)
- `def test_wizard_repairs_broken_yaml_via_retry(cfg, target: Path) -> None` (строка 171)
- `def test_wizard_accepts_bare_task_list(cfg, target: Path) -> None` (строка 191)
- `def test_normalize_dir_scope_gets_glob() -> None` (строка 211)
- локальные импорты: `forge/lint.py`, `forge/llm.py`, `forge/models.py`, `forge/profiles.py`, `forge/wizard.py`
