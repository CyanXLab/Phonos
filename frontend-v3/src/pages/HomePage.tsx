export function HomePage() {
  return (
    <div className="space-y-6">
      <div className="card">
        <h1 className="text-2xl font-bold mb-2">Phonos 听说训练系统 v3</h1>
        <p className="text-gray-600 dark:text-gray-300">
          本地优先的英语听说训练系统，重点适配上海中考/高考英语听说训练场景。
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <FeatureCard
          title="发音评测 v2"
          desc="9 维评分：音素准确度/完整度/流利度/韵律/重音/语调/停顿/语速/音质"
          to="/practice"
        />
        <FeatureCard
          title="听写训练 v2"
          desc="词级对齐 + 拼写容错 + 音近词 + 关键词权重 + 语法变形识别"
          to="/dictation"
        />
        <FeatureCard
          title="上海听说考试"
          desc="9 种任务类型：朗读/听写/听答/信息转述/情景应答/看图说话/模拟套卷"
          to="/shanghai-exam"
        />
      </div>

      <div className="card bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800">
        <h3 className="font-semibold text-yellow-800 dark:text-yellow-200 mb-1">合规声明</h3>
        <p className="text-sm text-yellow-700 dark:text-yellow-300">
          本系统提供的所有评分为辅助评估，非官方成绩，仅供参考。评分基于本地 AI 模型，
          可能与人工评分存在偏差。建议结合教师反馈综合判断。Phonos 与上海市教育考试院无任何关联。
        </p>
      </div>

      <div className="card">
        <h3 className="font-semibold mb-3">技术特性</h3>
        <ul className="text-sm space-y-1 text-gray-600 dark:text-gray-300">
          <li>✓ 本地优先：默认所有数据本地处理，不上传用户音频</li>
          <li>✓ 多 Provider：本地 HuPER（默认）+ Azure/讯飞/有道（可选）</li>
          <li>✓ 强制对齐：CTC segmentation 输出音素/单词级时间戳</li>
          <li>✓ 置信度加权：模型置信度参与评分</li>
          <li>✓ FSRS-6 间隔重复 + 错误驱动学习</li>
          <li>✓ 隐私安全：可随时导出/删除全部数据</li>
          <li>✓ PWA 离线：核心功能可离线使用</li>
        </ul>
      </div>
    </div>
  );
}

function FeatureCard({ title, desc, to }: { title: string; desc: string; to: string }) {
  return (
    <a href={to} className="card hover:shadow-md transition-shadow block">
      <h3 className="font-semibold mb-2 text-primary-600">{title}</h3>
      <p className="text-sm text-gray-600 dark:text-gray-300">{desc}</p>
    </a>
  );
}
