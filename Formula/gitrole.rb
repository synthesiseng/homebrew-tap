class Gitrole < Formula
  desc "Switch your full git identity in one command"
  homepage "https://docs.gitrole.dev"
  url "https://registry.npmjs.org/gitrole/-/gitrole-0.10.3.tgz"
  sha256 "5faef2d1f05f07603bc56d8c8fb21155a6065389c991a23fa8b6b401ff3d36d8"
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
