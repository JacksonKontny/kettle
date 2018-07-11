import configparser
import datetime
import json
import random
import time

import langdetect
from langdetect.lang_detect_exception import LangDetectException
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from nltk import tokenize
from pymongo import MongoClient
from steembase.exceptions import PostDoesNotExist
from steem import Steem

config = configparser.ConfigParser()
config.read('config.ini')
POSTING_KEY = config['steem']['posting_key']
ACCOUNT = config['steem']['account']
POST_CATEGORIES = set([
    'altcoin', 'bitshares', 'btc', 'business', 'crypto-news', 'curation',
    'esteem', 'happy', 'steemit', 'bitcoin', 'introduceyourself', 'cryptocurrency', 'steem',
    'blog', 'funny', 'news', 'dlive', 'dtube', 'dmania', 'crypto', 'money',
    'blockchain', 'technology', 'science', 'sports'
])


def convert_post_datetime(post_datetime_str):
    return datetime.datetime.strptime(
        post_datetime_str, "%Y-%m-%dT%H:%M:%S.000Z")

def datetime_filter(start_time, end_time=None):
    if not end_time:
        end_time = datetime.datetime.now()
    end_time = end_time + datetime.timedelta(hours=6)
    start_time = start_time + datetime.timedelta(hours=6)
    return {"created": {"$gte": start_time, "$lte": end_time}}

def vote_count_filter(vote_count):
    return {"$where": "this.active_votes.length > {}".format(vote_count)}

class SteemClient(object):
    def __init__(self, posting_key=POSTING_KEY, account=ACCOUNT):
        self.account = account
        self.steem = Steem(keys=[posting_key])

    def stream_fresh_posts(self, is_main=True, allow_votes=True, expiration_minutes=15):
        """
        Retrieves posts filtered by the input criteria.

        * Args
            * is_main -> boolean that designates if comments should be filtered out
            * allow_votes -> boolean that designates if posts that do not allow
                votes should be filtered out
            * expiration_minutes -> integer defining how old a post can be before
                filtering it out

        """
        stream = self.steem.stream_comments()
        while True:
            try:
                post = next(stream)
                if (
                        (not is_main or post.is_main_post())
                        and (not allow_votes or post.allow_votes)
                        and post.time_elapsed() < datetime.timedelta(
                            minutes=expiration_minutes
                        ) and langdetect.detect(post.body) == 'en'
                        and post.category in POST_CATEGORIES
                ):
                    yield post
            except PostDoesNotExist as exception:
                print('post does not exist exception... moving on')
            except LangDetectException as exception:
                try:
                    print('language in post not understood:\n\n{}'.format(post.body))
                except:
                    print('couldnt even print out post body')
            except Exception as e:
                print(e)
                stream = self.steem.stream_comments()

    def comment_on_post(self, post, comment):
        post.reply(author=self.account, body=comment, title=self.account)
        time.sleep(20)

class MongoSteem(object):

    def __init__(self, host_name='mongodb://localhost/test', db_name='test', steem_client=None):
        if steem_client is None:
            steem_client = SteemClient()
        self.steem_client = steem_client
        mongo_client = MongoClient(host_name)
        self.db = getattr(mongo_client, db_name)


    def store_post(self, post):
        post_data = post.__dict__
        del post_data['steem']
        self.db.posts.insert_one(post_data)

    def stream_posts_from_mongo(self, query=None, limit=None):
        if query is None:
            query = {}
        post_query = self.db.posts.find(query)
        if limit:
            post_query = post_query.limit(limit)
        try:
            for post_data in post_query:
                yield Post(post_data['identifier'], steem_instance=self.steem_client.steem)

        except Exception as e:
            print(e)

    def update_post(self, post):
        post_data = post.__dict__
        del post_data['steem']
        self.db.posts.update_one(
            {'identifier': post.identifier},
            {'$set': post_data}
        )

    def update_posts(self, query=None):
        if not query:
            query = {}
        for post in self.stream_posts_from_mongo(query=query):
            self.update_post(post)


class PostSentiment(object):
    def __init__(self, post):
        self.sid = SentimentIntensityAnalyzer()
        self.post = post

    @property
    def tokens(self):
        return tokenize.sent_tokenize(self.post.body)

    @property
    def polarities(self):
        polarities = []
        for token in self.tokens:
            polarities.append(self.sid.polarity_scores(token))
        return polarities

    @property
    def normalized_polarities(self):
        return [pol['pos'] - pol['neg'] for pol in self.polarities]

    @property
    def neg_polarity_sentence(self):
        return self.tokens[
            self.normalized_polarities.index(min(self.normalized_polarities))
        ]

    @property
    def pos_polarity_sentence(self):
        return self.tokens[
            self.normalized_polarities.index(max(self.normalized_polarities))
        ]

    @property
    def overall_polarity(self):
        overall_polarity = {}
        for key in ['pos', 'neg', 'neu', 'compound']:
            average = round(
                sum([pol[key] for pol in self.polarities]) / len(self.polarities),
                3
            )
            overall_polarity[key] = average
        return overall_polarity

    @property
    def negative_polarity_description(self):
        if min(self.normalized_polarities) < 0:
            return (
                'The most negative sentence in your post had a normalized '
                'negativity score of {}:\n\n"{}"\n\n'.format(
                    min(self.normalized_polarities),
                    self.neg_polarity_sentence
                )
            )
        return ''

    @property
    def positive_polarity_description(self):
        if max(self.normalized_polarities) > 0:
            return (
                'The most positive sentence in your post had a normalized '
                'positivity score of {}:\n\n"{}"\n\n'.format(
                    max(self.normalized_polarities),
                    self.pos_polarity_sentence
                )
            )
        return ''

    @property
    def overall_polarity_description(self):
        return (
            'Your post had an average negative sentiment of -{}, '
            'an average positive sentiment of {}, and an average normalized '
            'sentiment of {}\n\n'.format(
                self.overall_polarity['neg'],
                self.overall_polarity['pos'],
                sum(self.normalized_polarities) / len(self.normalized_polarities)
            )
        )

    @property
    def intro(self):
        return (
            'Thanks for the post, {post_author}.\n\n'
            'I hope you don\'t mind if I test out some sentiment analysis on '
            'your post.  This is an experimental bot running on a small % of '
            'posts, and if reaction is positive I\'ll increase that ratio and '
            'add features.\n\n'.format(
                post_author=self.post.author
            )
        )

    @property
    def description(self):
        if self.overall_polarity['neg'] or self.overall_polarity['pos']:
            return '{}{}{}{}'.format(
                self.intro,
                self.overall_polarity_description,
                self.positive_polarity_description,
                self.negative_polarity_description,
            )
        return ''

    def get_max_polarity(self, pole='neg'):
        polarity_values = [polarity[pole] for polarity in self.polarities]
        return max(polarity_values)

    @property
    def to_csv(self):
        return ','.join([
            str(max(self.normalized_polarities)),
            str(min(self.normalized_polarities)),
            round(
                str(sum(self.normalized_polarities) / len(self.normalized_polarities)),
                2
            ),
        ]) + '\n'


class PostMiner(object):

    def __init__(self, category=None, expiration_minutes=60, sleep_time=60):
        self.category = category
        self.expiration_minutes = expiration_minutes
        self.sleep_time = sleep_time
        self.detected_winners = []
        self.mongo_steem = MongoSteem()

    def mine_winners(self):
        while True:
            winning_post_query = self.get_target_query()
            winning_post_query.update(vote_count_filter(3))
            winning_post_query.update({"identifier": {"$nin": self.detected_winners}})
            winner_query = self.mongo_steem.db.posts.find(
                winning_post_query, {"identifier": 1}
            )
            winners = [winner['identifier'] for winner in winner_query]
            self.detected_winners.extend(winners)
            yield winners

            time.sleep(self.sleep_time)
            self.update_target_posts()

    def update_target_posts(self):
        update_post_query = self.get_target_query()
        print('running update query {}'.format(datetime.datetime.now()))
        self.mongo_steem.update_posts(query=update_post_query)

    def get_target_query(self):
        target_query = {"category": self.category}
        target_query.update(datetime_filter(
            start_time=datetime.datetime.now() - datetime.timedelta(minutes=self.expiration_minutes)
        ))
        return target_query

class SteemSentimentCommenter(object):
    def __init__(self, post_percent=.02, article_word_count=500):
        self.steem_client = SteemClient()
        self.post_percent = post_percent
        self.article_word_count = 500

    def run(self):
        for post in self.steem_client.stream_fresh_posts():
            if len(post.body.split(' ')) > self.article_word_count:
                with open('post_sentiment.csv', 'a+') as fh:
                    sent = PostSentiment(post)
                    fh.write(sent.to_csv)

                if random.random() < self.post_percent:
                    self.comment(post)

    def comment(self, post):
        post_sentiment = PostSentiment(post)
        try:
            if post_sentiment.description:
                self.steem_client.comment_on_post(post, post_sentiment.description)
                print('https://steemit.com{}'.format(post.url))
                print(post_sentiment.description)
        except Exception as e:
            print(e)


class SteemVoter(object):
    def __init__(self, mongo_steem=None, post_miner=None, vote_limit=11, run_hours=24):
        if not mongo_steem:
            mongo_steem = MongoSteem()
        if not post_miner:
            post_miner = PostMiner()
        self.mongo_steem = mongo_steem
        self.post_miner = post_miner
        self.vote_limit = vote_limit
        self.upvoted_winners = []
        self.end_time = datetime.datetime.now() + datetime.timedelta(hours=run_hours)

    def daily_run(self):
        while not self.post_quota_met:
            for winner_group in self.post_miner.mine_winners():
                self.upvote_winners(winner_group)

    def upvote_winners(self, winners):
        for winner in winners:
            if len(self.upvoted_winners) < self.vote_limit:
                winning_post = Post(winner, steem_instance=self.mongo_steem.steem_client.steem)
                winning_post.upvote(voter=self.mongo_steem.steem_client.voter)
                self.upvoted_winners.append(winner)
                print('winning post: {}'.format(winner))

                # cannot post two consecutive votes less than 3 seconds apart
                time.sleep(3)

    @property
    def post_quota_met(self):
        return len(self.upvoted_winners) >= self.vote_limit or datetime.datetime.now() > self.end_time


if __name__ == '__main__':
    commenter = SteemSentimentCommenter()
    commenter.run()
