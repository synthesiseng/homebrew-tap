class Gitrole < Formula
  desc "Switch Git name/email and load a saved SSH key when configured"
  homepage "https://docs.gitrole.dev"
  url "https://registry.npmjs.org/gitrole/-/gitrole-0.13.4.tgz"
  sha256 "dc8acaeae9976b85cdc2818cfcba3bab5b23126a2649d9ad356e77f920d560f4"
  license "MIT"

  depends_on "node"

  def install
    system "npm", "install", *std_npm_args
    bin.install_symlink Dir["#{libexec}/bin/*"]
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/gitrole --version")
    sample = "role=work scope=na override=na commit=ok remote=na auth=na policy=na overall=aligned\n"
    assert_match "gitrole:work ✓", pipe_output("#{bin}/gitrole-prompt --format", sample)
  end
end
