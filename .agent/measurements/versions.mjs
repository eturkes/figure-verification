import { loadPyodide } from "pyodide";

const pyodide = await loadPyodide();
await pyodide.loadPackage(["numpy", "pandas"]);
const versions = pyodide.runPython(`
import json, platform, sys
import numpy, pandas, pyodide
json.dumps({
    "python": sys.version,
    "platform": platform.platform(),
    "pyodide": pyodide.__version__,
    "numpy": numpy.__version__,
    "pandas": pandas.__version__,
})
`);
console.log(versions);
