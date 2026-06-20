{
  lib,
  buildPythonPackage,
  fetchurl,
  python,
  lxml,
  cryptography,
  certifi,
  fpdf2,
  defusedxml,
}:

let
  version = "7.9.2";

  # fintech ships a bytecode-only wheel per CPython minor version (no sdist),
  # so the right wheel has to be selected for the interpreter pretix runs on.
  wheels = {
    "3.11" = {
      url = "https://files.pythonhosted.org/packages/2b/d1/7250db64280df7ec548bf1428d0dfbf0b0204c88b4bb09c3155e84a69e94/fintech-7.9.2-cp311-none-any.whl";
      hash = "sha256-b2MqflO8+mi3a3pGOeNhteWGvFDV2gu0X75svzk+D6Q=";
    };
    "3.12" = {
      url = "https://files.pythonhosted.org/packages/a2/1b/79838401f78bbef5413c7bee6e1e1d278ad443cac40495001b0e715e8682/fintech-7.9.2-cp312-none-any.whl";
      hash = "sha256-LC+fE3fgfsP+UH/MnOWaiXxpzg7A3uw/3sPx6sB3HLM=";
    };
    "3.13" = {
      url = "https://files.pythonhosted.org/packages/b9/28/65ab4c74538bfc5be3f2fc009f3439bb8b5b824229d54f2e8133b5e2f615/fintech-7.9.2-cp313-none-any.whl";
      hash = "sha256-diuWB4U/c+xnGgd/kHBeT+OCNXkOYYnVwAfUfd+TPH4=";
    };
    "3.14" = {
      url = "https://files.pythonhosted.org/packages/92/69/70466e0a89b21c27641338057c9b9423063e7d5c39fa49c1f18f384e5d0b/fintech-7.9.2-cp314-none-any.whl";
      hash = "sha256-LwYk/EO+60nURa+PeuB+yeWTRo7zKrSFbOhD1mCU9hA=";
    };
  };

  wheel =
    wheels.${python.pythonVersion}
      or (throw "fintech: no wheel packaged for Python ${python.pythonVersion}");
in
buildPythonPackage {
  pname = "fintech";
  inherit version;
  format = "wheel";

  src = fetchurl { inherit (wheel) url hash; };

  dependencies = [
    lxml
    cryptography
    certifi
    fpdf2
    defusedxml
  ];

  pythonImportsCheck = [ "fintech" ];

  meta = {
    description = "Python package for SEPA, EBICS and other financial technologies";
    homepage = "https://www.joonis.de/en/fintech/";
    license = lib.licenses.unfree;
  };
}
