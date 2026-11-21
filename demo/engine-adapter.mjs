import path from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { execute, inputError } from "./process.mjs";
import { spawn } from "node:child_process";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export default {
  name: "Longform Video Engine",
  actions: ["validate", "render"],
  status: async () => ({
    available: true,
    capabilities: ["Native script contract", "Remotion chapter preview"],
    narrationConnected: false,
  }),
  async run(action, data, { directory, id }) {
    if (
      typeof data.title !== "string" ||
      !data.title.trim() ||
      data.title.length > 200 ||
      !Array.isArray(data.chapters) ||
      data.chapters.length !== 2 ||
      data.chapters.some(
        (c, i) =>
          c?.id !== `C0${i + 1}` ||
          typeof c.title !== "string" ||
          c.title.length > 150 ||
          typeof c.spoken_text !== "string" ||
          c.spoken_text.length > 20000,
      ) ||
      !Number.isFinite(data.wpm) ||
      data.wpm < 105 ||
      data.wpm > 190
    )
      throw inputError(
        "Provide two chapters and a reading pace between 105 and 190 words per minute.",
      );
    const result = await execute(
      process.env.DEMO_PYTHON || "python",
      ["-B", path.join(root, "demo/engine_runner.py")],
      { ...data, id },
      { cwd: root },
    );
    const contract = path.join(directory, "approved-script.json");
    writeFileSync(contract, JSON.stringify(result.contract, null, 2));
    const files = [
      {
        name: "approved-script.json",
        path: contract,
        mime: "application/json",
      },
    ];
    if (action === "render") {
      if (data.scriptHash !== result.contract.script_hash)
        throw inputError(
          "The script changed. Validate and lock this revision before rendering.",
        );
      const props = JSON.parse(
        readFileSync(
          path.join(root, "docs/examples/render-props.json"),
          "utf8",
        ),
      );
      props.runId = result.contract.run_id;
      props.durationMs = 12000;
      props.shots = data.chapters.map((c, i) => ({
        ...props.shots[0],
        shotId: `S000${i + 1}`,
        chapterId: c.id,
        startMs: i * 6000,
        endMs: (i + 1) * 6000,
        screenCopy: c.title,
        subcopy: c.spoken_text
          .trim()
          .split(/(?<=[.!?])\s+/)[0]
          .slice(0, 160),
      }));
      const propsPath = path.join(directory, "render-props.json");
      writeFileSync(propsPath, JSON.stringify(props));
      const target = path.join(directory, "chapter-preview.mp4"),
        args = [
          path.join(
            root,
            "remotion/node_modules/@remotion/cli/remotion-cli.js",
          ),
          "render",
          "src/index.ts",
          "Longform",
          target,
          `--props=${propsPath}`,
          "--log=error",
          "--concurrency=2",
          "--muted",
        ];
      if (process.env.DEMO_CHROME_PATH) {
        if (!existsSync(process.env.DEMO_CHROME_PATH))
          throw inputError(
            "The configured browser for rendering is unavailable.",
          );
        args.push(`--browser-executable=${process.env.DEMO_CHROME_PATH}`);
      }
      if (process.env.DEMO_REMOTION_BINARIES)
        args.push(`--binaries-directory=${process.env.DEMO_REMOTION_BINARIES}`);
      await new Promise((resolve, reject) => {
        const child = spawn(process.execPath, args, {
          cwd: path.join(root, "remotion"),
          windowsHide: true,
          stdio: ["ignore", "pipe", "pipe"],
        });
        let logs = "";
        const timer = setTimeout(() => {
          child.kill();
          reject(
            Object.assign(Error("Render timed out"), {
              code: "engine_timeout",
              userMessage:
                "Rendering took too long. The validated script is safe.",
            }),
          );
        }, 240000);
        child.stdout.on("data", (c) => {
          logs = (logs + c).slice(-100000);
        });
        child.stderr.on("data", (c) => {
          logs = (logs + c).slice(-100000);
        });
        child.on("error", (e) => {
          clearTimeout(timer);
          reject(e);
        });
        child.on("close", (code) => {
          clearTimeout(timer);
          writeFileSync(path.join(directory, "private-render.log"), logs);
          code === 0
            ? resolve()
            : reject(Error("Renderer failed. See private run log."));
        });
      });
      files.push({
        name: "chapter-preview.mp4",
        path: target,
        mime: "video/mp4",
      });
      result.preview = {
        durationSeconds: 12,
        narration: false,
        scope:
          "Silent chapter storyboard rendered from the current locked script. This is not a full narrated film.",
      };
    }
    return { result, files };
  },
};
