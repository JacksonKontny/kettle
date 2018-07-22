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
from steem.post import Post

config = configparser.ConfigParser()
config.read('config.ini')
POSTING_KEY = config['steem']['posting_key']
POSITIVE_THRESHOLD = config['steem']['positive_threshold']
NEGATIVE_THRESHOLD = config['steem']['negative_threshold']
ACCOUNT = config['steem']['account']
POST_CATEGORIES = set([
    'altcoin', 'bitshares', 'btc', 'business', 'crypto-news', 'curation',
    'esteem', 'happy', 'steemit', 'bitcoin', 'introduceyourself', 'cryptocurrency', 'steem',
    'blog', 'funny', 'news', 'dlive', 'dtube', 'dmania', 'crypto', 'money',
    'blockchain', 'technology', 'science', 'sports'
])
SPAM_DETECTORS = set(['badcontent'])


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
                        # and post.category in POST_CATEGORIES
                ):
                    yield post
            except PostDoesNotExist as exception:
                print('post does not exist exception... moving on')
            except LangDetectException as exception:
                try:
                    print('language in post not understood')
                except:
                    print('couldnt even print out post body')
            except Exception as e:
                print(e)
                stream = self.steem.stream_comments()

    def comment_on_post(self, post, comment):
        try:
            post.reply(author=self.account, body=comment, title=self.account)
            time.sleep(20)
        except Exception as e:
            print(e)

    def upvote_post(self, post):
        try:
            post.upvote(voter=self.account)
        except Exception as e:
            print(e)

    def write_post(self, title, body, tags):
        self.steem.commit.post(
            author=self.account,
            body=body,
            tags=tags,
        )

    def is_post_spam(self, post):
        replies = post.get_replies()
        for reply in replies:
            if reply.author in SPAM_DETECTORS:
                return True


class MongoSteem(object):

    def __init__(self, host='localhost', port=27017, db_name='steem', collection_name='posts'):
        mongo_client = MongoClient(host, port)
        db = getattr(mongo_client, db_name)
        self.collection = getattr(db, collection_name)

    def get_post_data_for_storage(self, post):
        export = post.export()
        export['tags'] = list(export['tags'])
        return export

    def store_post(self, post, additional_data=None):
        post_data = self.get_post_data_for_storage(post)
        if additional_data:
            post_data.update(additional_data)
        self.collection.insert_one(post_data)

    def stream_posts_from_mongo(self, query=None, limit=None, raw=False):
        if query is None:
            query = {}
        post_query = self.collection.find(query)
        if limit:
            post_query = post_query.limit(limit)
        try:
            for post_data in post_query:
                if raw:
                    yield post_data
                else:
                    yield Post(post_data)

        except Exception as e:
            print(e)

    def update_post(self, post):
        post.refresh()
        self.collection.update_one(
            {'identifier': post.identifier},
            {'$set': self.get_post_data_for_storage(post)}
        )

    def update_posts(self, query=None):
        if not query:
            query = {}
        for post in self.stream_posts_from_mongo(query=query):
            self.update_post(post)

    def is_post_new(self, post):
        return bool(self.collection.find_one({'id': post.id}, {'_id': 1}))


class PostSentiment(object):
    def __init__(self, post):
        self.sid = SentimentIntensityAnalyzer()
        self.post = post
        self.negative_threshold = NEGATIVE_THRESHOLD
        self.positive_threshold = POSITIVE_THRESHOLD

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
                str(self.avg_normalized_polarity),
            )
        )

    @property
    def intro(self):
        return (
            'Thanks for the post, {post_author}.\n\n'
            'This bot runs through hundreds of posts per day selecting a small '
            'percentage of posts that have exceptional positivity.\n\n'.format(
                post_author=self.post.author
            )
        )

    @property
    def reason_for_posting(self):
        return (
            'Your post has been selected and upvoted because it has a high '
            'concentration of positive words that give feel-good vibes. '
            'My bot and I would like to thank you for creating content that '
            'focuses on the bright side.\n\n'
            'In the future your post will be included in a curated list posted '
            'at the end of the day that includes positive content\n\n'
        )

    @property
    def vote_comment(self):
        return (
            'Please comment \'yes\' or \'no\' if you feel that my bot is '
            'correct in its judgement of this post.  Your comments will be '
            'used to improve performance.\n\n'
        )

    @property
    def description(self):
        return '{}{}{}'.format(
            self.intro,
            self.reason_for_posting,
            self.vote_comment,
        )

    @property
    def avg_normalized_polarity(self):
        return round(
            sum(self.normalized_polarities) / len(self.normalized_polarities),
            2
        )

    def get_max_polarity(self, pole='neg'):
        polarity_values = [polarity[pole] for polarity in self.polarities]
        return max(polarity_values)

    @property
    def to_csv(self):
        return ','.join([
            str(max(self.normalized_polarities)),
            str(min(self.normalized_polarities)),
            str(self.avg_normalized_polarity),
        ]) + '\n'

    @property
    def to_mongo(self):
        return {
            'polarities': self.polarities,
            'normalized_polarities': self.normalized_polarities,
            'overall_polarity': self.overall_polarity,
        }

    @property
    def is_neg_outlier(self):
        return self.avg_normalized_polarity <= self.negative_threshold

    @property
    def is_pos_outlier(self):
        return self.avg_normalized_polarity >= self.positive_threshold


class SteemSentimentCommenter(object):
    def __init__(self, article_word_count=500):
        self.steem_client = SteemClient()
        self.article_word_count = 500
        self.post_list = []
        self.mongo_steem = MongoSteem()

    def run(self):
        for post in self.steem_client.stream_fresh_posts():
            if (
                len(post.body.split(' ')) > self.article_word_count
                and self.mongo_steem.is_post_new(post)
            ):
                sentiment = PostSentiment(post)
                self.save_sentiment(sentiment)
                self.handle_interaction_with_content_provider(sentiment)
            if datetime.datetime.now().hour == 13 and len(self.post_list) == 9:
                self.write_positive_article_post()

    def save_sentiment(self, sentiment):
        with open('post_sentiment.csv', 'a+') as fh:
            fh.write(sentiment.to_csv)
        self.mongo_steem.store_post(
            sentiment.post,
            additional_data=sentiment.to_mongo
        )

    def handle_interaction_with_content_provider(self, post_sentiment):
        if post_sentiment.is_pos_outlier:
            post_sentiment.post.refresh()
            if (
                # post_sentiment.post.net_votes >= 3 and
                not self.steem_client.is_post_spam(post_sentiment.post)
            ):
                self.steem_client.upvote_post(post_sentiment.post)
                self.steem_client.comment_on_post(
                    post_sentiment.post,
                    post_sentiment.description,
                )
                self.post_list.append(self.get_steemit_url(post_sentiment.post))
                print(self.get_steemit_url(post_sentiment.post))
                print(post_sentiment.description)
                print('posts in list: {}'.format(len(self.post_list)))

    def get_steemit_url(self, post):
        return 'https://steemit.com{}'.format(post.url)

    def write_positive_article_post(self):
        title = 'Top positive articles of the day - {}'.format(str(datetime.date.today()))
        intro = (
            "Below are the top uplifting posts of the day.  These posts have "
            "been selected due to their overwhelming positive word choice. The "
            "articles listed have more positive words than 99.5% of articles "
            "posted in english on the steemit platform.  Go ahead and give these "
            "articles a read and see if they can improve your life, inspire you and improve "
            "your day:\n\n"
        )
        links = '\n\n'.join(self.post_list)
        self.post_list = []
        body = '{}{}'.format(intro, links)
        tags = ['life', 'motivation', 'inspiration', 'happy', 'good-karma']
        self.steem_client.write_post(title, body, tags)


if __name__ == '__main__':
    commenter = SteemSentimentCommenter()
    commenter.run()
