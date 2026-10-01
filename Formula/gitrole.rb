class Gitrole < Formula
  desc "Switch your full git identity in one command"
  homepage "https://docs.gitrole.dev"
  url "https://registry.npmjs.org/gitrole/-/gitrole-0.10.5.tgz"
  sha256 "bc53257eea356ed24f664505ccc420887ab8be0e3135abfd529087b664bf0362"
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
