import {Config} from "@remotion/cli/config";

Config.setOverwriteOutput(true);
Config.setPublicDir(process.env.REMOTION_PUBLIC_DIR || "public");
